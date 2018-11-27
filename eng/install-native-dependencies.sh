#!/usr/bin/env sh

if [ "$1" = "Linux" ]; then
    sudo apt update
    if [ "$?" != "0" ]; then
       exit 1;
    fi
    sudo apt install cmake llvm-3.9 clang-3.9 lldb-3.9 liblldb-3.9-dev libunwind8 libunwind8-dev gettext libicu-dev liblttng-ust-dev libcurl4-openssl-dev libssl-dev libkrb5-dev libnuma-dev
    if [ "$?" != "0"]; then
        exit 1;
    fi
elif [ "$1" = "OSX" ]; then
    if [ -x "$(command -v brew)" ]; then
        brew install icu4c openssl
         
        if [ "$?" != "0" ]; then
            exit 1;
        fi
        brew link --force icu4c
        if [ "$?" != "0"]; then
            exit 1;
        fi
    else
        # Setup clang
        mkdir -p ~/bin
        pushd ~/bin
        curl -O http://releases.llvm.org/3.9.0/clang+llvm-3.9.0-x86_64-apple-darwin.tar.xz
        tar xzf clang+llvm-3.9.0-x86_64-apple-darwin.tar.xz
        echo PATH=~/bin/clang+llvm-3.9.0-x86_64-apple-darwin/bin >> ~/.bash_profile
        source ~/.bash_profile

        PROC_COUNT=`getconf _NPROCESSORS_ONLN`
        mkdir /tmp/icu_build
        pushd /tmp/icu_build
        pwd
        curl -O http://download.icu-project.org/files/icu4c/58.2/icu4c-58_2-src.tgz
        tar xzf icu4c-58_2-src.tgz
        cd icu/source
        ls
        ./configure
        make -j ${PROC_COUNT}
        sudo make install

    fi
    else
    echo "Must pass \"Linux\" or \"OSX\" as first argument."
    exit 1
fi

