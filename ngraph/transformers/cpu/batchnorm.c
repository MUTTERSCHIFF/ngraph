/*******************************************************************************
* Copyright 2017-2018 Intel Corporation
*
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.
*******************************************************************************/

#include "mkldnn_engine.h"
#include "mkldnn_util.h"

/* Create list of mkldnn primitives to run batch norm fprop */
void create_mkldnn_batchnorm_fprop_primitives(
    mkldnn_engine_t engine, int src_dims, int dst_dims, int weights_dims,
    int mean_dims, int variance_dims, int mean_sizes, int variance_sizes,
    int *batchnorm_src_sizes, int *batchnorm_weights_sizes,
    int *batchnorm_dst_sizes, double epsilon,
    mkldnn_memory_desc_t* input_src_md,
    mkldnn_memory_desc_t* input_weights_md,
    mkldnn_data_type_t data_type,
    mkldnn_opkernel_t opkernel) {

  int mkl_mean_sizes[1];
  int mkl_variance_sizes[1];
  mkl_mean_sizes[0] = mean_sizes;
  mkl_variance_sizes[0] = variance_sizes;

  //-------------------------------------------------------------------------------

  mkldnn_batch_normalization_desc_t batch_norm_desc;
  MKL_CHECK(mkldnn_batch_normalization_forward_desc_init(
      &batch_norm_desc, mkldnn_forward_training, input_src_md,
      epsilon, mkldnn_use_scaleshift));

  //-------------------------------------------------------------------------------
  /* create a batch norm primitive descriptor - bound to the CPU engine */
  MKL_CHECK(mkldnn_primitive_desc_create(&opkernel->op_desc, &batch_norm_desc,
                                         engine, NULL));

  //-------------------------------------------------------------------------------
  /* Query input and dst memory descriptor from batchnorm Op descriptor*/
  const_mkldnn_primitive_desc_t kernel_src_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_src_pd, 0);
  const_mkldnn_primitive_desc_t kernel_dst_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_dst_pd, 0);

  //-------------------------------------------------------------------------------
  /* create a  memory descriptor for the input, mean, variance, weights,
   * outputs*/
  if (input_src_md) {
    create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, input_src_md, engine,
                                 &(opkernel->inputs[0]));
  } else {
    create_mkldnn_tensor(src_dims, batchnorm_src_sizes, data_type, mkldnn_chwn,
                         engine, &(opkernel->inputs[0]));
  }

  if (input_weights_md) {
    create_mkldnn_tensor_from_md(weights_dims, batchnorm_weights_sizes, input_weights_md,
                                 engine, &(opkernel->inputs[1]));
  } else {
    create_mkldnn_tensor(weights_dims, batchnorm_weights_sizes, data_type,
                         mkldnn_nc, engine, &(opkernel->inputs[1]));
  }

  mkldnn_memory_desc_t dst_md =
      *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
  create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, &dst_md, engine,
                               &(opkernel->outputs[0]));
  create_mkldnn_tensor(mean_dims, mkl_mean_sizes, data_type, mkldnn_x, engine,
                       &(opkernel->outputs[1]));
  create_mkldnn_tensor(variance_dims, mkl_variance_sizes, data_type, mkldnn_x,
                       engine, &(opkernel->outputs[2]));
  //-------------------------------------------------------------------------------
  // check if reorder's are required for inputs of batchnorm
  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[0].desc,
                                          kernel_src_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_src_pd);
    create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, &md, engine,
                                 &(opkernel->internal_inputs[0]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[0].desc, kernel_src_pd));
    mkldnn_primitive_at_t inputs[] = {
        mkldnn_primitive_at(opkernel->inputs[0].prim, 0)};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[0].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[0]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[0] = NULL;
  }

  //-------------------------------------------------------------------------------
  /* Allocate memory for internal format conversions
     NOTE: output primitive for fprop batchnorm jit implementation uses vmovntps
          instruction, so the allocated memory needs to be 64bytes aligned */
  if (opkernel->reorder_i[0]) {
    void *tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(batchnorm_src_sizes, src_dims),
                         data_type, 64);
    opkernel->internal_inputs[0].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[0].prim,
                                            tmp_buf));
  }

  //-------------------------------------------------------------------------------
  /* select input and output primitives based on reorders */
  mkldnn_primitive_t mkldnn_memory_prim_src =
      opkernel->reorder_i[0] ? opkernel->internal_inputs[0].prim
                             : opkernel->inputs[0].prim;

  opkernel->num_inputs = 2;
  opkernel->num_outputs = 3;

  // No reorders required
  opkernel->reorder_i[1] = NULL;
  opkernel->reorder_o[0] = NULL;
  opkernel->reorder_o[1] = NULL;
  opkernel->reorder_o[2] = NULL;

  //-------------------------------------------------------------------------------
  /* create fprop batch norm primitive */
  const_mkldnn_primitive_t batch_norm_prim_dsts[] = {
      opkernel->outputs[0].prim,
      opkernel->outputs[1].prim,
      opkernel->outputs[2].prim
      };
  mkldnn_primitive_at_t batch_norm_prim_srcs[] = {
      mkldnn_primitive_at(mkldnn_memory_prim_src, 0),
      mkldnn_primitive_at(opkernel->inputs[1].prim, 0)};

  MKL_CHECK(mkldnn_primitive_create(&opkernel->op_prim, opkernel->op_desc,
                                    batch_norm_prim_srcs,
                                    batch_norm_prim_dsts));
  //-------------------------------------------------------------------------------
  /* create fprop batchnorm net */
  if (opkernel->reorder_i[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[0];

  opkernel->net[opkernel->net_size++] = opkernel->op_prim;
}

void create_mkldnn_batchnorm_bprop_primitives(
    mkldnn_engine_t engine, int src_dims, int dst_dims, int weights_dims,
    int mean_dims, int variance_dims, int *batchnorm_src_sizes,
    int *batchnorm_dst_sizes, int *batchnorm_weights_sizes, int mean_sizes,
    int variance_sizes, double epsilon,
    mkldnn_memory_desc_t* input_fprop_src_md,
    mkldnn_memory_desc_t* input_weights_md,
    mkldnn_memory_desc_t* input_mean_md,
    mkldnn_memory_desc_t* input_variance_md,
    mkldnn_memory_desc_t* input_error_md, mkldnn_data_type_t data_type,
    mkldnn_opkernel_t fprop_kernel, mkldnn_opkernel_t opkernel) {

  int mkl_mean_sizes[1];
  int mkl_variance_sizes[1];
  mkl_mean_sizes[0] = mean_sizes;
  mkl_variance_sizes[0] = variance_sizes;

  //-------------------------------------------------------------------------------
  /*  create bprop batchnorm descriptor
      Note: flags: mkldnn_use_scaleshift, prop_kind: mkldnn_backward
      computes gradient w.r.to data only during bprop
      flags: mkldnn_use_scaleshift, prop_kind: mkldnn_backward computes gradient
      w.r.to data, gamma, beta during bprop */
  mkldnn_batch_normalization_desc_t batch_norm_desc;
  // MKLDNN seems to prefer the same layout for inputs and delta
  MKL_CHECK(mkldnn_batch_normalization_backward_desc_init(
      &batch_norm_desc, mkldnn_backward, input_fprop_src_md, input_fprop_src_md, epsilon,
      mkldnn_use_scaleshift));

  MKL_CHECK(mkldnn_primitive_desc_create(&opkernel->op_desc, &batch_norm_desc,
                                         engine, fprop_kernel->op_desc));
  //-------------------------------------------------------------------------------
  /* query the gradient and source primitive descriptor for batchnorm bprop op
     desc this will be used to check if reorder is required or not for
     delta(error)
     and fprop src*/
  const_mkldnn_primitive_desc_t kernel_fprop_src_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_src_pd, 0);
  const_mkldnn_primitive_desc_t kernel_src_pd = mkldnn_primitive_desc_query_pd(
      opkernel->op_desc, mkldnn_query_diff_dst_pd, 0);
  const_mkldnn_primitive_desc_t kernel_dst_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_src_pd, 0);
  const_mkldnn_primitive_desc_t kernel_diff_weights_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_weights_pd, 0);

  //-------------------------------------------------------------------------------
  /* create a  memory descriptor for the fprop_src_input, mean, variance,
     gradients, weights, outputs*/
  if (input_fprop_src_md) {
    create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, input_fprop_src_md, engine,
                                 &(opkernel->inputs[0]));
  } else {
    create_mkldnn_tensor(src_dims, batchnorm_src_sizes, data_type, mkldnn_chwn,
                         engine, &(opkernel->inputs[0]));
  }

  if (input_mean_md) {
    create_mkldnn_tensor_from_md(mean_dims, mkl_mean_sizes, input_mean_md, engine,
                                 &(opkernel->inputs[1]));
  } else {
    create_mkldnn_tensor(mean_dims, mkl_mean_sizes, data_type, mkldnn_x, engine,
                         &(opkernel->inputs[1]));
  }

  if (input_variance_md) {
    create_mkldnn_tensor_from_md(variance_dims, mkl_variance_sizes, input_variance_md, engine,
                                 &(opkernel->inputs[2]));
  } else {
    create_mkldnn_tensor(variance_dims, mkl_variance_sizes, data_type, mkldnn_x,
                         engine, &(opkernel->inputs[2]));
  }

  if (input_error_md) {
    create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, input_error_md, engine,
                                 &(opkernel->inputs[3]));
  } else {
    create_mkldnn_tensor(src_dims, batchnorm_src_sizes, data_type, mkldnn_chwn,
                         engine, &(opkernel->inputs[3]));
  }

  if (input_weights_md) {
    create_mkldnn_tensor_from_md(weights_dims, batchnorm_weights_sizes, input_weights_md,
                                 engine, &(opkernel->inputs[4]));
  } else {
    create_mkldnn_tensor(weights_dims, batchnorm_weights_sizes, data_type,
                         mkldnn_nc, engine, &(opkernel->inputs[4]));
  }

  mkldnn_memory_desc_t dst_md =
        *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
  create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, &dst_md, engine,
                                 &(opkernel->outputs[0]));
  mkldnn_memory_desc_t kernel_diff_weights_md =
        *mkldnn_primitive_desc_query_memory_d(kernel_diff_weights_pd);
  create_mkldnn_tensor_from_md(weights_dims, batchnorm_weights_sizes,
                               &kernel_diff_weights_md, engine, &(opkernel->outputs[1]));

  opkernel->num_inputs = 5;
  opkernel->num_outputs = 2;

  // No reorders required
  opkernel->reorder_i[1] = NULL;
  opkernel->reorder_i[2] = NULL;
  opkernel->reorder_i[4] = NULL;
  opkernel->reorder_o[0] = NULL;
  opkernel->reorder_o[1] = NULL;

  //-------------------------------------------------------------------------------
  // check if reorders is required for delta and fprop batchnorm inputs and
  // output
  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[0].desc,
                                          kernel_fprop_src_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_fprop_src_pd);
    create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, &md, engine,
                                 &(opkernel->internal_inputs[0]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[0].desc, kernel_fprop_src_pd));
    mkldnn_primitive_at_t inputs[] = {opkernel->inputs[0].prim};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[0].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[0]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[0] = NULL;
  }
  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[3].desc,
                                          kernel_src_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_src_pd);
    create_mkldnn_tensor_from_md(src_dims, batchnorm_src_sizes, &md, engine,
                                 &(opkernel->internal_inputs[3]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[3].desc, kernel_src_pd));
    mkldnn_primitive_at_t inputs[] = {opkernel->inputs[3].prim};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[3].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[3]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[3] = NULL;
  }

  //-------------------------------------------------------------------------------
  /* Allocate memory for internal format conversions
     NOTE: gradient primitive for bprop batchnorm jit implementation uses
     vmovntps
           instruction, so the allocated memory needs to be 64bytes aligned */
  if (opkernel->reorder_i[0]) {
    void *tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(batchnorm_src_sizes, src_dims),
                         data_type, 64);
    opkernel->internal_inputs[0].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[0].prim,
                                            tmp_buf));
  }
  if (opkernel->reorder_i[3]) {
    void *tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(batchnorm_src_sizes, src_dims),
                         data_type, 64);
    opkernel->internal_inputs[3].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[3].prim,
                                            tmp_buf));
  }

  //-------------------------------------------------------------------------------
  /* select input and output primitives based on reorders */
  mkldnn_primitive_t mkldnn_memory_prim_fprop_src =
      opkernel->reorder_i[0] ? opkernel->internal_inputs[0].prim
                             : opkernel->inputs[0].prim;
  mkldnn_primitive_t mkldnn_memory_prim_src =
      opkernel->reorder_i[3] ? opkernel->internal_inputs[3].prim
                             : opkernel->inputs[3].prim;

  mkldnn_primitive_t mkldnn_memory_prim_dst =
      opkernel->reorder_o[0] ? opkernel->internal_outputs[0].prim
                             : opkernel->outputs[0].prim;
  mkldnn_primitive_t mkldnn_memory_prim_diff_weights =
      opkernel->reorder_o[1] ? opkernel->internal_outputs[1].prim
                             : opkernel->outputs[1].prim;


  //-------------------------------------------------------------------------------
  /* create bprop batch norm primitive */
  const_mkldnn_primitive_t batch_norm_dsts[] = {mkldnn_memory_prim_dst, mkldnn_memory_prim_diff_weights};
  mkldnn_primitive_at_t batch_norm_srcs[] = {
      mkldnn_primitive_at(mkldnn_memory_prim_fprop_src, 0),
      mkldnn_primitive_at(opkernel->inputs[1].prim, 0),
      mkldnn_primitive_at(opkernel->inputs[2].prim, 0),
      mkldnn_primitive_at(mkldnn_memory_prim_src, 0),
      mkldnn_primitive_at(opkernel->inputs[4].prim, 0)};
  MKL_CHECK(mkldnn_primitive_create(&opkernel->op_prim, opkernel->op_desc,
                                    batch_norm_srcs, batch_norm_dsts));
  //-------------------------------------------------------------------------------
  /* create bprop batchnorm net */
  if (opkernel->reorder_i[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[0];
  if (opkernel->reorder_i[3])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[3];

  opkernel->net[opkernel->net_size++] = opkernel->op_prim;

  if (opkernel->reorder_o[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_o[0];
  if (opkernel->reorder_o[1])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_o[1];
}
