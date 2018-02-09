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

void create_mkldnn_conv_fprop_kernel(mkldnn_engine_t engine, int src_dims,
                                     int weights_dims, int bias_dims, int dst_dims,
                                     int* src_sizes, int* weights_sizes, int* bias_sizes,
                                     int* dst_sizes, int* strides, int* padding, int* dilates,
                                     mkldnn_memory_desc_t* input_src_md,
                                     mkldnn_memory_desc_t* input_weights_md,
                                     mkldnn_data_type_t data_type,
                                     mkldnn_opkernel_t opkernel) {
  // Create an optimized convolution kernel
  // Let MKL pick the best format (mkldnn_any)
  mkldnn_memory_desc_t mkldnn_memory_desc_src_md, mkldnn_memory_desc_weights_md,
      mkldnn_memory_desc_dst_md, mkldnn_memory_desc_bias_md;
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_src_md, src_dims,
                                    src_sizes, data_type, mkldnn_any));
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_weights_md,
                                    weights_dims, weights_sizes, data_type,
                                    mkldnn_any));
  int * bias_desc = NULL;
  if (bias_sizes)
  {
    MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_bias_md, bias_dims,
                                      bias_sizes, data_type, mkldnn_x));
    bias_desc = &mkldnn_memory_desc_bias_md;
  }
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_dst_md, dst_dims,
                                    dst_sizes, data_type, mkldnn_any));
  mkldnn_convolution_desc_t conv_desc;
  if (dilates[0] != 0 || dilates[1] != 0) {
    MKL_CHECK(mkldnn_dilated_convolution_forward_desc_init(
      &conv_desc, mkldnn_forward, mkldnn_convolution_direct,
      &mkldnn_memory_desc_src_md, &mkldnn_memory_desc_weights_md, bias_desc,
      &mkldnn_memory_desc_dst_md, strides, dilates, padding, padding,
      mkldnn_padding_zero));
  }
  else {
    MKL_CHECK(mkldnn_convolution_forward_desc_init(
      &conv_desc, mkldnn_forward, mkldnn_convolution_direct,
      &mkldnn_memory_desc_src_md, &mkldnn_memory_desc_weights_md, bias_desc,
      &mkldnn_memory_desc_dst_md, strides, padding, padding,
      mkldnn_padding_zero));
  }

  MKL_CHECK(mkldnn_primitive_desc_create(&opkernel->op_desc, &conv_desc, engine,
                                         NULL));

  const_mkldnn_primitive_desc_t kernel_src_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_src_pd, 0);
  const_mkldnn_primitive_desc_t kernel_weights_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_weights_pd,
                                     0);
  const_mkldnn_primitive_desc_t kernel_bias_pd;
  if (bias_sizes)
  {
    kernel_bias_pd =
        mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_weights_pd, 1);
  } 
  const_mkldnn_primitive_desc_t kernel_dst_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_dst_pd, 0);

  if (input_src_md) {
    create_mkldnn_tensor_from_md(src_dims, src_sizes, input_src_md, engine,
                                 &(opkernel->inputs[0]));
  } else {
    create_mkldnn_tensor(src_dims, src_sizes, data_type, mkldnn_chwn, engine,
                         &(opkernel->inputs[0]));
  }
  if (input_weights_md) {
    // MKL prefers ihwo nomenclature for filter layouts. chwn an ihwo are equivalent
    if (input_weights_md->format == mkldnn_chwn) input_weights_md->format = mkldnn_ihwo;
    create_mkldnn_tensor_from_md(weights_dims, weights_sizes, input_weights_md, engine,
                                 &(opkernel->inputs[1]));
  } else {
    create_mkldnn_tensor(weights_dims, weights_sizes, data_type, mkldnn_ihwo,
                         engine, &(opkernel->inputs[1]));
  }
 
  if (bias_sizes)
  {
    create_mkldnn_tensor(bias_dims, bias_sizes, data_type, mkldnn_x,
                           engine, &(opkernel->inputs[2]));
  }

  mkldnn_memory_desc_t dst_md =
      *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
  create_mkldnn_tensor_from_md(dst_dims, dst_sizes, &dst_md, engine,
                               &(opkernel->outputs[0]));
  // create_mkldnn_tensor(dst_dims, dst_sizes, data_type, mkldnn_chwn,
  //                     engine, &(opkernel->outputs[0]));
  if (bias_sizes)
    opkernel->num_inputs = 3;
  else
    opkernel->num_inputs = 2; 
  opkernel->num_outputs = 1;

  // Reorder inputs
  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[0].desc,
                                          kernel_src_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_src_pd);
    create_mkldnn_tensor_from_md(src_dims, src_sizes, &md, engine,
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

  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[1].desc,
                                          kernel_weights_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_weights_pd);
    create_mkldnn_tensor_from_md(weights_dims, weights_sizes, &md, engine,
                                 &(opkernel->internal_inputs[1]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[1].desc, kernel_weights_pd));
    mkldnn_primitive_at_t inputs[] = {
        mkldnn_primitive_at(opkernel->inputs[1].prim, 0)};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[1].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[1]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[1] = NULL;
  }

  if (bias_sizes)
  {
    if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[2].desc,
                                            kernel_bias_pd)) {
      mkldnn_memory_desc_t md =
          *mkldnn_primitive_desc_query_memory_d(kernel_bias_pd);
      create_mkldnn_tensor_from_md(bias_dims, bias_sizes, &md, engine,
                                 &(opkernel->internal_inputs[2]));
      mkldnn_primitive_desc_t reorder_pd;
      MKL_CHECK(mkldnn_reorder_primitive_desc_create(
          &reorder_pd, opkernel->inputs[2].desc, kernel_bias_pd));
      mkldnn_primitive_at_t inputs[] = {
          mkldnn_primitive_at(opkernel->inputs[2].prim, 0)};
      const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[2].prim};
      MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[2]), reorder_pd,
                                        inputs, outputs));
    } else {
      opkernel->reorder_i[2] = NULL;
    }
  }


  if (!mkldnn_memory_primitive_desc_equal(opkernel->outputs[0].desc,
                                          kernel_dst_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
    create_mkldnn_tensor_from_md(src_dims, src_sizes, &md, engine,
                                 &(opkernel->internal_outputs[0]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->outputs[0].desc, kernel_dst_pd));
    mkldnn_primitive_at_t inputs[] = {
        mkldnn_primitive_at(opkernel->internal_outputs[0].prim, 0)};
    const_mkldnn_primitive_t outputs[] = {opkernel->outputs[0].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_o[0]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_o[0] = NULL;
  }

  /* Allocate memory for internal format conversions */
  if (opkernel->reorder_i[0]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(src_sizes, src_dims), data_type, 64);
    opkernel->internal_inputs[0].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[0].prim,
                                            tmp_buf));
  }
  if (opkernel->reorder_i[1]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(weights_sizes, weights_dims), data_type, 64);
    opkernel->internal_inputs[1].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[1].prim,
                                            tmp_buf));
  }
  if(bias_sizes)
  {
    if (opkernel->reorder_i[2]) {
      void* tmp_buf;
      alloc_aligned_memory(&tmp_buf, product(bias_sizes, bias_dims), data_type, 64);
      opkernel->internal_inputs[2].buffer = tmp_buf;
      MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[2].prim,
                                              tmp_buf));
    }
  }

  if (opkernel->reorder_o[0]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(dst_sizes, dst_dims), data_type, 64);
    opkernel->internal_outputs[0].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_outputs[0].prim,
                                            tmp_buf));
  }

  /* select input and output primitives for convolution */
  mkldnn_primitive_t mkldnn_memory_prim_bias;
  mkldnn_primitive_t mkldnn_memory_prim_src =
      opkernel->reorder_i[0] ? opkernel->internal_inputs[0].prim
                             : opkernel->inputs[0].prim;
  mkldnn_primitive_t mkldnn_memory_prim_weights =
      opkernel->reorder_i[1] ? opkernel->internal_inputs[1].prim
                             : opkernel->inputs[1].prim;
  if (bias_sizes)
  {
    mkldnn_memory_prim_bias =
        opkernel->reorder_i[2] ? opkernel->internal_inputs[2].prim
                               : opkernel->inputs[2].prim;
  }
  mkldnn_primitive_t mkldnn_memory_prim_dst =
      opkernel->reorder_o[0] ? opkernel->internal_outputs[0].prim
                             : opkernel->outputs[0].prim;

  const_mkldnn_primitive_t conv_dsts[] = {mkldnn_memory_prim_dst};

  mkldnn_primitive_at_t conv_srcs[3];
  conv_srcs[0] = mkldnn_primitive_at(mkldnn_memory_prim_src, 0);
  conv_srcs[1] = mkldnn_primitive_at(mkldnn_memory_prim_weights, 0);

  if (bias_sizes) 
      conv_srcs[2] = mkldnn_primitive_at(mkldnn_memory_prim_bias, 0);
  
  MKL_CHECK(mkldnn_primitive_create(&opkernel->op_prim, opkernel->op_desc,
                                    conv_srcs, conv_dsts));

  if (opkernel->reorder_i[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[0];
  if (opkernel->reorder_i[1])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[1];
  if (bias_sizes)
  {
    if (opkernel->reorder_i[2])
       opkernel->net[opkernel->net_size++] = opkernel->reorder_i[2];
  }  
  opkernel->net[opkernel->net_size++] = opkernel->op_prim;
  if (opkernel->reorder_o[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_o[0];
}

void create_mkldnn_conv_bprop_data_kernel(
    mkldnn_engine_t engine, int src_dims, int weights_dims, int dst_dims,
    int* src_sizes, int* weights_sizes, int* dst_sizes, int* strides,
    int* padding, int* dilates, mkldnn_memory_desc_t* input_src_md,
    mkldnn_memory_desc_t* input_weights_md, mkldnn_data_type_t data_type,
    mkldnn_opkernel_t opkernel) {
  mkldnn_memory_desc_t mkldnn_memory_desc_src_md, mkldnn_memory_desc_weights_md,
      mkldnn_memory_desc_dst_md;
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_src_md, src_dims,
                                    src_sizes, data_type, mkldnn_any));
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_weights_md,
                                    weights_dims, weights_sizes, data_type,
                                    mkldnn_any));
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_dst_md, dst_dims,
                                    dst_sizes, data_type, mkldnn_any));
  mkldnn_convolution_desc_t conv_desc_data;
  if (dilates[0] != 0 || dilates[1] != 0) {
    MKL_CHECK(mkldnn_dilated_convolution_backward_data_desc_init(
      &conv_desc_data, mkldnn_convolution_direct, &mkldnn_memory_desc_dst_md,
      &mkldnn_memory_desc_weights_md, &mkldnn_memory_desc_src_md, strides,
      dilates, padding, padding, mkldnn_padding_zero));
  }
  else {
    MKL_CHECK(mkldnn_convolution_backward_data_desc_init(
        &conv_desc_data, mkldnn_convolution_direct, &mkldnn_memory_desc_dst_md,
        &mkldnn_memory_desc_weights_md, &mkldnn_memory_desc_src_md, strides,
        padding, padding, mkldnn_padding_zero));
  }
  MKL_CHECK(mkldnn_primitive_desc_create(&opkernel->op_desc, &conv_desc_data,
                                         engine, NULL));

  const_mkldnn_primitive_desc_t kernel_src_pd = mkldnn_primitive_desc_query_pd(
      opkernel->op_desc, mkldnn_query_diff_dst_pd, 0);
  const_mkldnn_primitive_desc_t kernel_weights_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_weights_pd,
                                     0);
  const_mkldnn_primitive_desc_t kernel_dst_pd = mkldnn_primitive_desc_query_pd(
      opkernel->op_desc, mkldnn_query_diff_src_pd, 0);

  if (input_src_md) {
    create_mkldnn_tensor_from_md(src_dims, src_sizes, input_src_md, engine,
                                 &(opkernel->inputs[0]));
  } else {
    create_mkldnn_tensor(src_dims, src_sizes, data_type, mkldnn_chwn, engine,
                         &(opkernel->inputs[0]));
  }
  if (input_weights_md) {
    // MKL prefers ihwo nomenclature for filter layouts. chwn an ihwo are equivalent
    if (input_weights_md->format == mkldnn_chwn) input_weights_md->format = mkldnn_ihwo;
    create_mkldnn_tensor_from_md(weights_dims, weights_sizes, input_weights_md, engine,
                                 &(opkernel->inputs[1]));
  } else {
    create_mkldnn_tensor(weights_dims, weights_sizes, data_type, mkldnn_ihwo,
                         engine, &(opkernel->inputs[1]));
  }
  mkldnn_memory_desc_t dst_md =
      *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
  create_mkldnn_tensor_from_md(dst_dims, dst_sizes, &dst_md, engine,
                               &(opkernel->outputs[0]));
  opkernel->num_inputs = 2;
  opkernel->num_outputs = 1;

  // Reorder inputs
  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[0].desc,
                                          kernel_src_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_src_pd);
    create_mkldnn_tensor_from_md(src_dims, src_sizes, &md, engine,
                                 &(opkernel->internal_inputs[0]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[0].desc, kernel_src_pd));
    mkldnn_primitive_at_t inputs[] = {opkernel->inputs[0].prim};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[0].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[0]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[0] = NULL;
  }

  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[1].desc,
                                          kernel_weights_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_weights_pd);
    create_mkldnn_tensor_from_md(weights_dims, weights_sizes, &md, engine,
                                 &(opkernel->internal_inputs[1]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[1].desc, kernel_weights_pd));
    mkldnn_primitive_at_t inputs[] = {opkernel->inputs[1].prim};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[1].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[1]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[1] = NULL;
  }

  // No reorder on the output side
  opkernel->reorder_o[0] = NULL;

  /* Allocate memory for internal format conversions */
  if (opkernel->reorder_i[0]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(src_sizes, src_dims), data_type, 64);
    opkernel->internal_inputs[0].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[0].prim,
                                            tmp_buf));
  }
  if (opkernel->reorder_i[1]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(weights_sizes, weights_dims), data_type, 64);
    opkernel->internal_inputs[1].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[1].prim,
                                            tmp_buf));
  }

  /* select input and output primitives for convolution */
  mkldnn_primitive_t mkldnn_memory_prim_src =
      opkernel->reorder_i[0] ? opkernel->internal_inputs[0].prim
                             : opkernel->inputs[0].prim;
  mkldnn_primitive_t mkldnn_memory_prim_weights =
      opkernel->reorder_i[1] ? opkernel->internal_inputs[1].prim
                             : opkernel->inputs[1].prim;
  mkldnn_primitive_t mkldnn_memory_prim_dst = opkernel->outputs[0].prim;

  const_mkldnn_primitive_t conv_dsts[] = {mkldnn_memory_prim_dst};

  /* create a convolution primitive */
  mkldnn_primitive_at_t conv_srcs[] = {
      mkldnn_primitive_at(mkldnn_memory_prim_src, 0),
      mkldnn_primitive_at(mkldnn_memory_prim_weights, 0)};

  MKL_CHECK(mkldnn_primitive_create(&opkernel->op_prim, opkernel->op_desc,
                                    conv_srcs, conv_dsts));

  if (opkernel->reorder_i[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[0];
  if (opkernel->reorder_i[1])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[1];
  opkernel->net[opkernel->net_size++] = opkernel->op_prim;
}

// src - diff_dst
// weights - diff_weights
// bias - diff_bias
// dst - fprop_src
void create_mkldnn_conv_bprop_weights_kernel(
    mkldnn_engine_t engine, int src_dims, int weights_dims, int bias_dims, 
    int dst_dims, int* src_sizes, int* weights_sizes, int* bias_sizes, 
    int* dst_sizes, int* strides, int* padding, int* dilates,
    mkldnn_memory_desc_t* input_src_md,
    mkldnn_memory_desc_t* output_weights_md,
    mkldnn_memory_desc_t* input_dst_md, mkldnn_data_type_t data_type,
    mkldnn_opkernel_t opkernel) {
  mkldnn_memory_desc_t mkldnn_memory_desc_src_md, mkldnn_memory_desc_dst_md,
      mkldnn_memory_desc_diff_bias_md, mkldnn_memory_desc_weights_md;
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_src_md, src_dims,
                                    src_sizes, data_type, mkldnn_any));
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_weights_md,
                                    weights_dims, weights_sizes, data_type,
                                    mkldnn_any));
  MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_dst_md, dst_dims,
                                    dst_sizes, data_type, mkldnn_any));
  if (bias_sizes) {
    MKL_CHECK(mkldnn_memory_desc_init(&mkldnn_memory_desc_diff_bias_md, bias_dims,
                                      bias_sizes, data_type, mkldnn_x));
  }

  mkldnn_convolution_desc_t conv_desc_weights;
  mkldnn_memory_desc_t* bias;
  bias = (bias_sizes) ? &mkldnn_memory_desc_diff_bias_md : NULL;
  if (dilates[0] != 0 || dilates[1] != 0) {
    MKL_CHECK(mkldnn_dilated_convolution_backward_weights_desc_init(
      &conv_desc_weights, mkldnn_convolution_direct, &mkldnn_memory_desc_dst_md,
      &mkldnn_memory_desc_weights_md, bias,
      &mkldnn_memory_desc_src_md, strides,
      dilates, padding, padding, mkldnn_padding_zero));
  }
  else { 
    MKL_CHECK(mkldnn_convolution_backward_weights_desc_init(
      &conv_desc_weights, mkldnn_convolution_direct, &mkldnn_memory_desc_dst_md,
      &mkldnn_memory_desc_weights_md, bias, &mkldnn_memory_desc_src_md,
      strides, padding, padding, mkldnn_padding_zero));
  }
  MKL_CHECK(mkldnn_primitive_desc_create(&opkernel->op_desc, &conv_desc_weights,
                                         engine, NULL));

  const_mkldnn_primitive_desc_t kernel_src_pd = mkldnn_primitive_desc_query_pd(
      opkernel->op_desc, mkldnn_query_diff_dst_pd, 0);
  const_mkldnn_primitive_desc_t kernel_weights_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc,
                                     mkldnn_query_diff_weights_pd, 0);
  const_mkldnn_primitive_desc_t kernel_dst_pd =
      mkldnn_primitive_desc_query_pd(opkernel->op_desc, mkldnn_query_src_pd, 0);

  if (input_src_md) {
    create_mkldnn_tensor_from_md(src_dims, src_sizes, input_src_md, engine,
                                 &(opkernel->inputs[0]));
  } else {
    create_mkldnn_tensor(src_dims, src_sizes, data_type, mkldnn_chwn, engine,
                         &(opkernel->inputs[0]));
  }
  if (input_dst_md) {
    create_mkldnn_tensor_from_md(dst_dims, dst_sizes, input_dst_md, engine,
                                 &(opkernel->inputs[1]));
  } else {
    create_mkldnn_tensor(dst_dims, dst_sizes, data_type, mkldnn_chwn, engine,
                         &(opkernel->inputs[1]));
  }
  if (output_weights_md) {
    // MKL prefers ihwo nomenclature for filter layouts. chwn an ihwo are equivalent
    if (output_weights_md->format == mkldnn_chwn) output_weights_md->format = mkldnn_ihwo;
    create_mkldnn_tensor_from_md(weights_dims, weights_sizes, output_weights_md, engine,
                                 &(opkernel->outputs[0]));
  } else {
    create_mkldnn_tensor(weights_dims, weights_sizes, data_type, mkldnn_ihwo,
                         engine, &(opkernel->outputs[0]));
  }
  
  if (bias_sizes)
  {
    create_mkldnn_tensor(bias_dims, bias_sizes, data_type, mkldnn_x,
                           engine, &(opkernel->outputs[1]));
  }

  opkernel->num_inputs = 2;
  opkernel->num_outputs = bias_sizes ? 2 : 1;

  // Reorder inputs
  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[0].desc,
                                          kernel_src_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_src_pd);
    create_mkldnn_tensor_from_md(src_dims, src_sizes, &md, engine,
                                 &(opkernel->internal_inputs[0]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[0].desc, kernel_src_pd));
    mkldnn_primitive_at_t inputs[] = {opkernel->inputs[0].prim};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[0].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[0]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[0] = NULL;
  }

  if (!mkldnn_memory_primitive_desc_equal(opkernel->inputs[1].desc,
                                          kernel_dst_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_dst_pd);
    create_mkldnn_tensor_from_md(dst_dims, dst_sizes, &md, engine,
                                 &(opkernel->internal_inputs[1]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, opkernel->inputs[1].desc, kernel_dst_pd));
    mkldnn_primitive_at_t inputs[] = {opkernel->inputs[1].prim};
    const_mkldnn_primitive_t outputs[] = {opkernel->internal_inputs[1].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_i[1]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_i[1] = NULL;
  }

  if (!mkldnn_memory_primitive_desc_equal(opkernel->outputs[0].desc,
                                          kernel_weights_pd)) {
    mkldnn_memory_desc_t md =
        *mkldnn_primitive_desc_query_memory_d(kernel_weights_pd);
    create_mkldnn_tensor_from_md(weights_dims, weights_sizes, &md, engine,
                                 &(opkernel->internal_outputs[0]));
    mkldnn_primitive_desc_t reorder_pd;
    MKL_CHECK(mkldnn_reorder_primitive_desc_create(
        &reorder_pd, kernel_weights_pd, opkernel->outputs[0].desc));
    mkldnn_primitive_at_t inputs[] = {opkernel->internal_outputs[0].prim};
    const_mkldnn_primitive_t outputs[] = {opkernel->outputs[0].prim};
    MKL_CHECK(mkldnn_primitive_create(&(opkernel->reorder_o[0]), reorder_pd,
                                      inputs, outputs));
  } else {
    opkernel->reorder_o[0] = NULL;
  }
  if (bias_sizes) 
    opkernel->reorder_o[1] = NULL;

  /* Allocate memory for internal format conversions */
  if (opkernel->reorder_i[0]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(src_sizes, src_dims), data_type, 64);
    opkernel->internal_inputs[0].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[0].prim,
                                            tmp_buf));
  }
  if (opkernel->reorder_i[1]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(dst_sizes, dst_dims), data_type, 64);
    opkernel->internal_inputs[1].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_inputs[1].prim,
                                            tmp_buf));
  }
  if (opkernel->reorder_o[0]) {
    void* tmp_buf;
    alloc_aligned_memory(&tmp_buf, product(weights_sizes, weights_dims), data_type, 64);
    opkernel->internal_outputs[0].buffer = tmp_buf;
    MKL_CHECK(mkldnn_memory_set_data_handle(opkernel->internal_outputs[0].prim,
                                            tmp_buf));
  }

  /* select input and output primitives for convolution */
  mkldnn_primitive_t mkldnn_memory_prim_src =
      opkernel->reorder_i[0] ? opkernel->internal_inputs[0].prim
                             : opkernel->inputs[0].prim;
  mkldnn_primitive_t mkldnn_memory_prim_dst =
      opkernel->reorder_i[1] ? opkernel->internal_inputs[1].prim
                             : opkernel->inputs[1].prim;
  mkldnn_primitive_t mkldnn_memory_prim_weights =
      opkernel->reorder_o[0] ? opkernel->internal_outputs[0].prim
                             : opkernel->outputs[0].prim;

  const_mkldnn_primitive_t conv_dsts[2];
  conv_dsts[0] = mkldnn_memory_prim_weights;
  if (bias_sizes)
      conv_dsts[1] = opkernel->outputs[1].prim;

  /* create a convolution primitive */
  mkldnn_primitive_at_t conv_srcs[] = {
      mkldnn_primitive_at(mkldnn_memory_prim_dst, 0),
      mkldnn_primitive_at(mkldnn_memory_prim_src, 0)};

  MKL_CHECK(mkldnn_primitive_create(&opkernel->op_prim, opkernel->op_desc,
                                    conv_srcs, conv_dsts));

  if (opkernel->reorder_i[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[0];
  if (opkernel->reorder_i[1])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_i[1];
  opkernel->net[opkernel->net_size++] = opkernel->op_prim;
  if (opkernel->reorder_o[0])
    opkernel->net[opkernel->net_size++] = opkernel->reorder_o[0];
}
