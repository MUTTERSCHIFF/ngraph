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
Approximate Planar Traveling Salesman Problem using Pointer Networks
Reference paper: https://arxiv.org/pdf/1506.03134.pdf
"""
from __future__ import division
from __future__ import print_function
from contextlib import closing
import ngraph as ng
from ngraph.frontends.neon import UniformInit, RMSProp, ax, Tanh, Logistic
from ngraph.frontends.neon import NgraphArgparser, make_bound_computation
from ngraph.frontends.neon import LSTM
import ngraph.transformers as ngt
from ngraph.frontends.neon.data.tsp import TSP
from tsp_seqarrayiter import TSPSequentialArrayIterator
from utils import save_plot

# parse the command line arguments
parser = NgraphArgparser(__doc__)
parser.add_argument('--train_file', default='tsp5.txt',
                    choices=['tsp5.txt', 'tsp10.txt'],
                    help='specify training filename')
parser.add_argument('--test_file', default='tsp5_test.txt',
                    choices=['tsp5_test.txt', 'tsp10_test.txt'],
                    help='specify testing filename')
parser.add_argument('--lr', type=float, default=0.0025, help='learning rate')
parser.add_argument('--hs', type=int, default=256, help='hidden unit size')
parser.add_argument('--emb', type=bool, default=True, help='use embedding')
parser.set_defaults()
args = parser.parse_args()
args.batch_size = 128
args.num_iterations = 20000

gradient_clip_value = 2
num_features = 2  # for planar TSP, each city's location is represented by a 2-d coordinate

# preprocess the TSP dataset
tsp = TSP(train_filename=args.train_file, test_filename=args.test_file)
tsp_data = tsp.load_data()

# number of time steps equal to number of points (cities) in each example
time_steps = tsp_data['train']['inp_txt'].shape[1]

# number of classes
ax.Y.length = time_steps

# create iterator and placeholders for training data
train_set = TSPSequentialArrayIterator(data_arrays=tsp_data['train'],
                                       nfeatures=num_features,
                                       batch_size=args.batch_size,
                                       time_steps=time_steps,
                                       total_iterations=args.num_iterations)
inputs = train_set.make_placeholders()

# weight initializationn
init = UniformInit(low=-0.08, high=0.08)

# build computational graph
enc = LSTM(args.hs, init, activation=Tanh(), reset_cells=True,
           gate_activation=Logistic(), return_sequence=True)
dec = LSTM(args.hs, init, activation=Tanh(), reset_cells=True,
           gate_activation=Logistic(), return_sequence=True)

if args.emb is True:
    # encoder input embedding
    hidden_feature_axis = ng.make_axis(length=args.hs, name='hidden_feature_axis')
    feature_axis = ng.make_axis(length=num_features, name='feature_axis')

    W_emb = ng.variable(axes=[hidden_feature_axis, feature_axis], initial_value=init)
    emb_enc_inputs = ng.dot(W_emb, inputs['inp_txt'])

    # decoder input embedding
    emb_dec_input = []
    ax.N.length = args.batch_size
    for i in range(ax.N.length):
        # for each iteration, permute (by true label)
        # encoder input embedding for teacher forcing input to decoder

        emb_enc_input = ng.slice_along_axis(emb_enc_inputs, axis=ax.N, idx=i)

        tmp_axis_1 = ng.make_axis(length=time_steps, name='tmp_axis_1')
        emb_enc_input_tmp = ng.cast_axes(emb_enc_input,
                                         ng.make_axes([hidden_feature_axis, tmp_axis_1]))
        perm = ng.slice_along_axis(inputs['tgt_txt'], axis=ax.N, idx=i)
        one_hot_target_tmp = ng.one_hot(perm, axis=tmp_axis_1)

        emb_dec_input.append(ng.dot(emb_enc_input_tmp, one_hot_target_tmp))

    emb_dec_inputs = ng.stack(emb_dec_input, axis=ax.N, pos=1)

    enc_input = emb_enc_inputs
    dec_input = emb_dec_inputs
else:
    enc_input = inputs['inp_txt']
    dec_input = inputs['teacher_txt']

(enc_h_out, enc_c_out) = enc(enc_input, return_cell_state=True)

# compute the last hidden/cell states as decoder's initial states
rec_axis = enc_h_out.axes.recurrent_axis()
enc_last_h_out = ng.slice_along_axis(enc_h_out, axis=rec_axis, idx=-1)
enc_last_c_out = ng.slice_along_axis(enc_c_out, axis=rec_axis, idx=-1)

dec_h_out = dec(dec_input, init_state=(enc_last_h_out, enc_last_c_out), return_cell_state=False)

# ptr-net model
rec_axis = dec_h_out.axes.recurrent_axis()
tmp_axis_2 = ng.make_axis(length=args.hs, name='tmp_axis_2')

# ptr-net variables
W1 = ng.variable(axes=[hidden_feature_axis, tmp_axis_2], initial_value=init)
W2 = ng.variable(axes=[hidden_feature_axis, tmp_axis_2], initial_value=init)
v = ng.variable(axes=[tmp_axis_2], initial_value=init)

input_time_steps = output_time_steps = time_steps

u_list = []  # a list of target probability distributions of every output time step
for i in range(output_time_steps):
    # compute attention vector for output time step i
    u_i_list = []  # a list of attention scores u_i
    W2_di = ng.dot(W2, ng.slice_along_axis(dec_h_out, axis=rec_axis, idx=i))

    for j in range(input_time_steps):
        # compute attention score for output time step i with input time step j
        W1_ej = ng.dot(W1, ng.slice_along_axis(enc_h_out, axis=rec_axis, idx=j))
        score = ng.dot(v, ng.tanh(W1_ej + W2_di))  # u_i = v * tanh(W1 * e_j + W2 * d_i)
        u_i_list.append(score)

    output_prob = ng.softmax(ng.stack(u_i_list, axis=ax.Y, pos=0), ax.Y)
    u_list.append(output_prob)

pointer_out = ng.stack(u_list, axis=rec_axis, pos=2)

# specify loss function, calculate loss and update weights
one_hot_target = ng.one_hot(inputs['tgt_txt'], axis=ax.Y)

loss = ng.cross_entropy_multi(pointer_out,
                              one_hot_target,
                              usebits=True)

mean_cost = ng.mean(loss, out_axes=[])
optimizer = RMSProp(decay_rate=0.96, learning_rate=args.lr, epsilon=1e-6,
                    gradient_clip_value=gradient_clip_value)
updates = optimizer(loss)

# provide outputs for bound computation
train_outputs = dict(batch_cost=mean_cost, updates=updates, pointer_out=pointer_out)

# Train Loop
with closing(ngt.make_transformer()) as transformer:
    # bind the computations
    train_computation = make_bound_computation(transformer, train_outputs, inputs)

    eval_frequency = 500
    loss = []
    # iterate over training set
    for idx, data in enumerate(train_set):
        train_output = train_computation(data)
        niter = idx + 1
        if niter % eval_frequency == 0:
            print('iteration = {}, train loss = {}'.format(niter, train_output['batch_cost']))

            loss.append(train_output['batch_cost'])
        niters = list(range(eval_frequency, niter + 1, eval_frequency))

save_plot(niters, loss, args)
