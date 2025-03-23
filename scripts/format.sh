#!/bin/bash

set -ex

cd packages/runtime
cargo fmt
cd ../..

prettier --write .
black .