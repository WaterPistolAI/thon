#!/bin/bash
git clone https://github.com/ggml-org/llama.cpp.git ~/llama.cpp
cd ~/llama.cpp
git pull origin master

sudo apt install cmake -y

rm -rf build
mkdir build && cd build
cd build

HIPCXX="$(hipconfig -l)/clang" \
HIP_PATH="$(hipconfig -R)" \
cmake -S .. -B . \
    -DGGML_HIP=ON \
    -DAMDGPU_TARGETS=gfx942 \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr/local \
    -DBUILD_SHARED_LIBS=ON \
&& cmake --build . --config Release -j20 \
&& sudo cmake --install .
sudo ldconfig
