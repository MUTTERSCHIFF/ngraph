#!/usr/bin/env python
# ******************************************************************************
# Copyright 2017-2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ******************************************************************************
"""
MNIST MLP with spelled out neon model framework in one file

The motivation is to show the flexibility of ngraph and how user can build a
model without the neon architecture. This may also help with debugging.

Run it using

python examples/mnist/mnist_mlp.py --data_dir /usr/local/data/MNIST --output_file out.hd5

"""
from __future__ import division
from __future__ import print_function
from contextlib import closing
import os
import numpy as np
import ngraph as ng
from ngraph.frontends.neon import Layer, Affine, Preprocess, Sequential
from ngraph.frontends.neon import GaussianInit, Rectlin, Logistic, GradientDescentMomentum
from ngraph.frontends.neon import ax, loop_train, make_bound_computation, make_default_callbacks
from ngraph.frontends.neon import loop_eval
from ngraph.frontends.neon import NgraphArgparser
from ngraph.frontends.neon import ArrayIterator

from ngraph.frontends.neon import MNIST
from ngraph.frontends.neon import Saver
import ngraph.transformers as ngt

parser = NgraphArgparser(description='Train simple mlp on mnist dataset')
parser.add_argument('--save_file', type=str, default=None, help="File to save weights")
parser.add_argument('--load_file', type=str, default=None, help="File to load weights")
parser.add_argument('--inference', action="store_true", help="Run Inference with loaded weight")
args = parser.parse_args()

if args.inference and (args.load_file is None):
    print("Need to set --load_file for Inference problem")
    quit()

if args.save_file is not None:
    save_file = os.path.expanduser(args.save_file)
else:
    save_file = None

if args.load_file is not None:
    load_file = os.path.expanduser(args.load_file)
else:
    load_file = None

np.random.seed(args.rng_seed)

# Create the dataloader
train_data, valid_data = MNIST(args.data_dir).load_data()
train_set = ArrayIterator(train_data, args.batch_size, total_iterations=args.num_iterations)
valid_set = ArrayIterator(valid_data, args.batch_size)

inputs = train_set.make_placeholders()
ax.Y.length = 10


######################
# Model specification
seq1 = Sequential([Preprocess(functor=lambda x: x / 255.),
                   Affine(nout=100, weight_init=GaussianInit(), activation=Rectlin()),
                   Affine(axes=ax.Y, weight_init=GaussianInit(), activation=Logistic())])

optimizer = GradientDescentMomentum(0.1, 0.9)
train_prob = seq1(inputs['image'])
train_loss = ng.cross_entropy_binary(train_prob, ng.one_hot(inputs['label'], axis=ax.Y))

batch_cost = ng.sequential([optimizer(train_loss), ng.mean(train_loss, out_axes=())])
train_outputs = dict(batch_cost=batch_cost)

with Layer.inference_mode_on():
    inference_prob = seq1(inputs['image'])
errors = ng.not_equal(ng.argmax(inference_prob, out_axes=[ax.N]), inputs['label'])
eval_loss = ng.cross_entropy_binary(inference_prob, ng.one_hot(inputs['label'], axis=ax.Y))
eval_outputs = dict(cross_ent_loss=eval_loss, misclass_pct=errors)

if (save_file is not None) or (load_file is not None):
    # Instantiate the Saver object to save weights
    weight_saver = Saver()

if not args.inference:
    # Now bind the computations we are interested in
    with closing(ngt.make_transformer()) as transformer:
        train_computation = make_bound_computation(transformer, train_outputs, inputs)
        loss_computation = make_bound_computation(transformer, eval_outputs, inputs)
        if load_file is not None:
            weight_saver.setup_restore(transformer=transformer, computation=train_outputs,
                                       filename=load_file)
            # Restore weight
            weight_saver.restore()
        if save_file is not None:
            weight_saver.setup_save(transformer=transformer, computation=train_outputs)
        cbs = make_default_callbacks(transformer=transformer,
                                     output_file=args.output_file,
                                     frequency=args.iter_interval,
                                     train_computation=train_computation,
                                     total_iterations=args.num_iterations,
                                     eval_set=valid_set,
                                     loss_computation=loss_computation,
                                     use_progress_bar=args.progress_bar)

        loop_train(train_set, train_computation, cbs)
        if save_file is not None:
            weight_saver.save(filename=save_file)
else:
    with closing(ngt.make_transformer()) as transformer:
        eval_computation = make_bound_computation(transformer, eval_outputs, inputs)
        weight_saver.setup_restore(transformer=transformer, computation=eval_outputs,
                                   filename=load_file)
        # Restore weight
        weight_saver.restore()
        eval_losses = loop_eval(valid_set, eval_computation)
        print("Inference complete.  Avg losses: " + str(eval_losses))
