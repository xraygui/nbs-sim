#! /usr/bin/bash
set -e
set -o xtrace

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
host_package_dir=$(dirname "$script_dir")/src

version="0.0.1"

container_package_dir=/usr/local/src
container_script_dir=/usr/local/bin

# Check if bluesky:latest image is available locally
if [[ "$(buildah images -q bluesky:latest)" == "" ]]; then
  echo "Image not found locally. Pulling from ghcr.io/nsls-ii-sst..."
  buildah pull ghcr.io/nsls-ii-sst/bluesky:latest
fi

container=$(buildah from bluesky:latest)
buildah run $container -- pip3 install git+https://github.com/NSLS-II-SST/sst_funcs.git@master
buildah run $container -- pip3 install git+https://github.com/NSLS-II-SST/sst_base.git@master

buildah copy $container $script_dir/run_dev.sh $container_script_dir 
buildah config --cmd "bash $container_script_dir/run_dev.sh" $container

buildah unmount $container
buildah commit $container nbs_sim:$version
buildah commit $container nbs_sim:latest
buildah rm $container
