legacy-README.md


As of January 03, 2018, this version of the project has a low level of activity. 
Bug patches will continue to be reviewed and accepted by the maintainer; however, 
new features will not be accepted. The code remains available for the community's 
use.
 

# nGraph library

nGraph library is Nervana's library for developing frameworks that can run deep
learning computations efficiently on a variety of compute platforms. It consists 
of three primary API components:

- An API for creating computational graphs.
- Two higher level frontend APIs (TensorFlow and Neon) utilizing the `ngraph` 
  library API for common deep learning workflows
- A transformer API for compiling these graphs and executing them.


## Installation

Installation documentation can be found
[here](https://ngraph.nervanasys.com/docs/latest/installation.html).

### MKL-DNN Support
To install with Intel MKL-DNN support, first download MKL-DNN from [here](https://github.com/01org/mkl-dnn) 
and follow the installation instructions there to install MKL-DNN. Set 
environment variable MKLDNN_ROOT to point to the installed location and 
follow the rest of the steps to install nGraph library.
```
export MKLDNN_ROOT=/path/to/mkldnn/root
```

### Multi-node Support
MPI is required for multi-node (multi-CPU and multi-GPU) support.  
Download Intel MPI from [here](https://software.intel.com/en-us/intel-mpi-library)
(select Linux OS, Intel MPI library product and go to 'Free Download' link).
Intel MPI package contains SDK part (headers and compiler scripts) required for mpi4py installation.

Install Intel MPI (use install.sh script from package).

Setup Intel MPI environment:
```
source <impi_install_path>/bin64/mpivars.sh
```
Intel MLSL is required for multi-CPU support in addtion to MPI.  
Download Intel MLSL from [here](https://github.com/intel/MLSL/releases).

Install Intel MLSL (follow the instructions [here](https://github.com/intel/MLSL/blob/master/README.md)).

Setup Intel MLSL environment:
```
source <mlsl_install_path>/intel64/bin/mlslvars.sh
```
Then, run
```
make multinode_prepare
```

### nGraph library installation
We recommend installing nGraph library inside a virtual environment.

To create and activate a Python 3 virtualenv:
```
python3 -m venv .venv
. .venv/bin/activate
```

To, instead, create and activate a Python 2.7 virtualenv:
```
virtualenv -p python2.7 .venv
. .venv/bin/activate
```

To install nGraph library:
```
make install
```

To add GPU support:
```
make gpu_prepare
```

To uninstall nGraph library:
```
make uninstall
```

To run the tests:
```
make [test_cpu|test_mkldnn|test_gpu|test_integration]
```

Before checking in code, ensure no "make style" errors:
```
make style
```

To fix style errors:
```
make fixstyle
```

To generate the documentation as html files:
```
sudo apt-get install pandoc
make doc
```

## Examples

* ``examples/walk_through/`` contains several code walk throughs.
* ``examples/mnist/mnist_mlp.py`` uses the neon front-end to define and train a MLP model on MNIST data.
* ``examples/cifar10/cifar10_conv.py`` uses the neon front-end to define and train a CNN model on CIFAR10 data.
* ``examples/cifar10/cifar10_mlp.py`` uses the neon front-end to define and train a MLP model on CIFAR10 data.
* ``examples/ptb/char_rnn.py`` uses the neon front-end to define and train a character-level RNN model on Penn Treebank data.

## Overview

### Frontends
- The neon frontend offers an improved interface for increased composability/flexibility
  while leaving common use cases easy. We demonstrate this with MLP, convolutional, and
  RNN network examples on MNIST, CIFAR10, and Penn Treebank datasets.
- The TensorFlow importer allows users to import existing tensorflow graphs and execute
  them using nGraph library transformers/runtimes. This importer currently only supports a
  subset of the TensorFlow API, but this will be expanded over time.

### nGraph library API
- The nGraph library API consists of a collection of graph building functions all exposed
  in the `ngraph` module/namespace. (eg: `ngraph.sum(...)`)
- We include walkthrough examples to use this API for logistic regression and multilayer
  perceptron classification of MNIST digit images.
- With the introduction of named `Axes` we lay the foundation for frontend writers to
  reason about tensor axis without concern of memory layout or order (for future
  optimization against hardware targets which often have differing and specific
  requirements for batch axis orderings for example).

### Transformer API
- This release ships with two example transformers targetting CPU and GPU hardware targets. 
- Both transformers support memory usage optimization passes.
- The GPU transformer also includes preliminary support for automatic kernel
  fusion/compounding for increased performance.
- Transformers allow users to register an included set of optional compiler passes for
  debug and visualization.
- The compiler pass infrastructure is slated to offer frontends/users similar flexibility
  to what LLVM library offers for general purpose compilation.

### Known Issues
These are known issues which are being addressed:

- The transformer fusion and memory sharing optimizations are currently hampered by some
  of the tensor dimension reshaping introduced by the existing lowering passes. Thus both
  are turned off by default.
- RNNs don't work well with longer sequences (longer than 30).

## Highlighted Future Work

- nGraph library serialization/deserialization.
- Further improvements/abstractions to graph composability for usability/optimization.
- Distributed, heterogeneous backend target support.
- C APIs for interoperability to enable other languages to create/execute graphs.
- Better debugging
- Support for model deployment

## Join Us
Please feel free to [contribute](CONTRIBUTING.rst) in shaping the future of nGraph library.



