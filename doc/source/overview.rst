.. _overview:

.. ---------------------------------------------------------------------------
.. Copyright 2017 Intel Corporation
.. Licensed under the Apache License, Version 2.0 (the "License");
.. you may not use this file except in compliance with the License.
.. You may obtain a copy of the License at
..
..      http://www.apache.org/licenses/LICENSE-2.0
..
.. Unless required by applicable law or agreed to in writing, software
.. distributed under the License is distributed on an "AS IS" BASIS,
.. WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
.. See the License for the specific language governing permissions and
.. limitations under the License.
.. ---------------------------------------------------------------------------

Overview
========

.. Note::
   We are currently transitioning the Intel® nGraph™ codebase from Python to 
   C++. As of January 03, 2018, this version of the project has a low level of 
   activity. Bug patches will continue to be reviewed and accepted by the 
   maintainer; however, new features will not be accepted. The code remains available 
   for the community's use.

Intel® Nervana™ Graph (nGraph™) is a Python library for implementing programs 
that convert descriptions of neural networks into programs that run efficiently 
on a variety of platforms. In designing Intel Nervana Graph we kept three guiding 
motivations in mind:

#  A modular and flexible library designed around a unifying computational graph 
   to empower users with composable deep learning abstractions.

#. Execution of these models with maximal computational efficiency without 
   worrying about details such as kernel fusion/compounding or data layout.

#. Enabling all of this on any user's hardware, whether they have one or multiple 
   CPUs, GPUs, and/or Intel AI portfolio solutions.

To achieve these goals, the nGraph™ library has three layers:

#. An API for creating computational nGraphs.

#. Two higher level frontend APIs (TensorFlow* and neon™) utilizing the 
   nGraph API for common deep learning workflows.

#. A transformer API for compiling these graphs and executing them on GPUs and CPUs.

   .. image:: assets/ngraph_workflow.png

Let's consider each of these layers in turn and the way they enable users.


Intel Nervana Graph
-------------------

The computational graphs of Theano* and TensorFlow* require a user to reason 
about the underlying tensor shapes while constructing the graph. This is 
tedious and error prone for the user and eliminates the ability for a compiler 
to reorder axes to match the assumptions of particular hardware platforms as 
well.

To simplify tensor management, the Intel Nervana Graph API enables users 
to define a set of named axes, attach them to tensors during graph construction, 
and specify them by name (rather than position) when needed.  These axes can 
be named according to the particular domain of the problem at hand to help a 
user with these tasks.  This flexibility then allows the necessary reshaping
or shuffling to be inferred by the transformer before execution. Additionally, 
these inferred tensor axis orderings can then be optimized across the entire 
computational graph for ordering preferences of the underlying runtimes/hardware 
platforms to optimize cache locality and runtime execution time.

These capabilities highlight one of the tenants of Intel Nervana Graph, which 
is to operate at a higher level of abstraction so transformers can make 
execution efficient without needing a "sufficiently smart compiler" that can 
reverse-engineer the higher level structure, as well as allowing users and 
frontends to more easily compose these building blocks together.


Frontends
---------

Most applications and users don't need the full flexibility offered by the 
nGraph API, so we are also introducing a higher level neon™ API that offers 
users a composable interface with the common building blocks to construct 
deep learning models. This includes things like common optimizers, metrics, 
and layer types such as linear, batch norm, convolutional, and RNN. We also 
illustrate these with example networks training on MNIST digits, CIFAR10 
images, and the Penn Treebank text corpus.

We also realize that users already know and use existing frameworks today 
and might want to continue using/combine models written in other frameworks. 
To that end, we demonstrate the capability to **convert existing TensorFlow 
models into Intel Nervana Graphs** and execute them using nGraph transformers. 
This importer supports a variety of common operation types today and will be 
expanding in future releases. We also plan on implementing compatibility with 
other frameworks in the near future, so stay tuned.

Additionally, we wish to stress that because nGraph offers the core building 
blocks of deep learning computation and multiple high performance backends, 
adding frontends is a straightforward affair and improvements to a backend 
(or new backends) are automatically leveraged by all existing and future 
frontends. So users get to keep using their preferred syntax while benefiting 
from the shared compilation machinery.

Transformers
------------

Making sure that models execute quickly with minimal memory overhead is 
critical given the millions or even billions of parameters and weeks of 
training time used by state-of-the-art models. Given our experience 
building and maintaining the fastest deep learning library on GPUs, we 
appreciate the complexities of modern deep learning performance:

- Kernel fusion/compounding
- Efficient buffer allocation
- Training vs. inference optimizations
- Heterogeneous backends
- Distributed training
- Multiple data layouts
- New hardware advancements (for example: Nervana Engine)

With these realities in mind, we designed nGraph transformers to automate 
and abstract these details away from frontends through clean APIs, while 
allowing power users room to tweak things all simultaneously without limiting 
the flexible abstractions for model creation.  In Intel Nervana Graph, we 
believe the key to achieving these goals rests in standing on the shoulders 
of giants in `modern compiler design <http://www.aosabook.org/en/llvm.html>`_ 
to promote flexibility and experimentation in choosing the set and order of 
compiler optimizations for a transformer to use.

Each nGraph transformer (or backend in LLVM parlance) targets a particular 
hardware backend and acts as an interface to compile an nGraph into a 
computation that is ready to be evaluated by the user as a function handle.

Today nGraph ships with a transformer for GPU and CPU execution, but in the 
future we plan on implementing heterogeneous device transformers with 
distributed training support.

Example
-------

For an example of building and executing nGraphs, refer to the 
:doc:`walkthrough<walk_throughs>` (work in progress). Below we have included 
a "hello world" example, which will print the numbers ``1`` through ``5``.

.. code:: python

    import nGraph as ng
    import nGraph.transformers as ngt

    # Build a graph
    x = ng.placeholder(())
    x_plus_one = x + 1

    # Construct a transformer
    transformer = ngt.make_transformer()

    # Define a computation
    plus_one = transformer.computation(x_plus_one, x)

    # Run the computation
    for i in range(5):
        print(plus_one(i))


Status and future work
----------------------

As this is a preview release, we have a lot of work left to do. Currently 
we include working examples of:

- MLP networks using MNIST and CIFAR-10.
- Convolutional networks using MNIST and CIFAR-10.
- RNN's using Penn Treebank.

We are actively working towards:

- Graph serialization/deserialization.
- Further improvements to graph composability for usability/optimization.
- Add additional support for more popular frontends.
- Distributed, heterogeneous backend target support.
- C APIs for interoperability to enable other languages to create/execute graphs.
- Modern, cloud native model deployment strategies.
- Reinforcement learning friendly `network construction <http://openreview.net/forum?id=r1Ue8Hcxg>`_ frontends.

Join us
-------
With the rapid pace in the deep learning community we realize that a 
project like this won't succeed without community participation, which 
is what motivated us to put this preview release out there to get feedback 
and encourage people like you to come join us in defining the next wave 
of deep learning tooling. Feel free to make pull requests / suggestions /
comments on `Github <https://github.com/NervanaSystems/nGraph>`_), or reach 
out to us on our `mailing list <https://groups.google.com/forum/#!forum/neon-users>`_. 
We are also hiring for full-time and internship positions.


