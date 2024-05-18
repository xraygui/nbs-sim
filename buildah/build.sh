#! /usr/bin/bash
set -e
set -o xtrace

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
host_package_dir=$(dirname "$script_dir")/src

version="0.0.1"

container_package_dir=/usr/local/src

# Check if bluesky:latest image is available locally
if [[ "$(buildah images -q bluesky:latest)" == "" ]]; then
  echo "Image not found locally. Pulling from ghcr.io/nsls-ii-sst..."
  buildah pull ghcr.io/nsls-ii-sst/bluesky:latest
fi

container=$(buildah from bluesky:latest)
buildah run $container -- pip3 install git+https://github.com/NSLS-II-SST/sst_funcs.git@reorganization
buildah run $container -- pip3 install git+https://github.com/NSLS-II-SST/sst_base.git@master

buildah copy $container $host_package_dir $container_package_dir 
buildah run --workingdir $container_package_dir $container -- pip3 install .

# this is the thing you want to change to spawn your IOC
buildah config --cmd "simline --list-pvs" $container
buildah unmount $container
buildah commit $container sim_beamline:$version
buildah commit $container sim_beamline:latest
buildah rm $container
