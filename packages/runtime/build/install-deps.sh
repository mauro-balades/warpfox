#!/bin/bash

set -ex

curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.81
. $HOME/.cargo/env

echo "All done!"
