#!/usr/bin/env python3
#
## Licensed to the .NET Foundation under one or more agreements.
## The .NET Foundation licenses this file to you under the MIT license.
## See the LICENSE file in the project root for more information.
#
##
# Title               : async_subprocess_helper.py
#
################################################################################
################################################################################

import asyncio
import multiprocessing
import os
import sys

################################################################################
################################################################################

class AsyncSubprocessHelper:
    def __init__(self, items, subproc_count=multiprocessing.cpu_count(), verbose=False):
        item_queue = asyncio.Queue()
        for item in items:
            item_queue.put_nowait(item)

        self.items = items
        self.subproc_count = int(subproc_count)
        self.verbose = verbose

        if 'win32' in sys.platform:
            # Windows specific event-loop policy & cmd
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    async def __get_item__(self, item, index, size, async_callback, *extra_args):
        """ Wrapper to the async callback which will schedule based on the queue
        """

        # Wait for the queue to become free. Then start
        # running the sub process.
        subproc_id = await self.subproc_count_queue.get()

        print_prefix = ""

        if self.verbose:
            print_prefix = "[{}:{}]: ".format(index, size)

        await async_callback(print_prefix, item, *extra_args)

        # Add back to the queue, incase another process wants to run.
        self.subproc_count_queue.put_nowait(subproc_id)

    async def __run_to_completion__(self, async_callback, *extra_args):
        """ async wrapper for run_to_completion
        """

        chunk_size = self.subproc_count

        # Create a queue with a chunk size of the cpu count
        #
        # Each run_pmi invocation will remove an item from the
        # queue before running a potentially long running pmi run.
        #
        # When the queue is drained, we will wait queue.get which
        # will wait for when a run_pmi instance has added back to the
        subproc_count_queue = asyncio.Queue(chunk_size)
        diff_queue = asyncio.Queue()

        for item in self.items:
            diff_queue.put_nowait(item)

        for item in range(chunk_size):
            subproc_count_queue.put_nowait(item)

        self.subproc_count_queue = subproc_count_queue
        tasks = []
        size = diff_queue.qsize()

        count = 1
        item = diff_queue.get_nowait() if not diff_queue.empty() else None
        while item is not None:
            tasks.append(self.__get_item__(item, count, size, async_callback, *extra_args))
            count += 1

            item = diff_queue.get_nowait() if not diff_queue.empty() else None

        await asyncio.gather(*tasks)

    def run_to_completion(self, async_callback, *extra_args):
        """ Run until the item queue has been depleted

             Notes:
            Acts as a wrapper to abstract the async calls to
            async_callback. Note that this will allow cpu_count 
            amount of running subprocesses. Each time the queue
            is emptied, another process will start. Note that
            the python code is single threaded, it will just
            rely on async/await to start subprocesses at
            subprocess_count
        """

        reset_env = os.environ.copy()
        asyncio.run(self.__run_to_completion__(async_callback, *extra_args))
        os.environ.update(reset_env)
