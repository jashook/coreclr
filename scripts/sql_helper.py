################################################################################
#
# Module: sql_helper.py
#
# Notes:
#
# Maintain a list of values that will be uploaded to an sql server. This is
# important because the current implementation of executemany is not performant.
# Therefore it is significantly faster to construct a single insert or execute
# statement with many combined values.
#
################################################################################

import pyodbc
import time

################################################################################
# sql_helper
################################################################################

class SqlHelper:
    def __init__(self, cursor, sql_statement, verbose = False):
        """ Ctor

        Notes:
                
            For a specific start constructing a set of values to eventually
            upload in batches. Max insert value size is 1k
        """

        self.cursor = cursor
        self.sql_statement = sql_statement
        self.values = []
        self.verbose = verbose
        self.size = None

        if len(self.values) >= 1000:
            self.__drain_queue__()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.__empty_queue__()

    def __drain_queue__(self):
        while len(self.values) >= 1000:
            batch = self.values[:1000]

            if len(self.values) >= 1000:
                self.values = self.values[1000:]

            start = time.perf_counter()

            command = self.create_command(batch)
            self.execute_command(command)
            elapsed_time = time.perf_counter() - start

    def __empty_queue__(self):
        if len(self.values) != 0:
            self.__drain_queue__()

            start = time.perf_counter()
            self.execute_command(self.create_command(self.values))
            elapsed_time = time.perf_counter() - start

    def add_data(self, value):
        if len(self.values) == 0 and self.size is None:
            self.size = len(value)
        else:
            assert len(value) == self.size

        self.values.append(value)

        if len(self.values) >= 1000:
            self.__drain_queue__()

    def create_command(self, batch):
        assert len(batch) <= 1000
        command = self.sql_statement.split("VALUES ")[0]
        
        new_list = []
        for insert_list in batch:
            new_values = [str(val) for val in insert_list]
            blah = []
            for index, val in enumerate(new_values):
                if index == 0:
                    val = "'{}'".format(val)

                else:
                    try:
                        val = int(val)
                    except:
                        val = "'{}'".format(val)

                blah.append(val)

            new_values = "("
            for val in blah:
                new_values = "{}{}, ".format(new_values, val)

            new_values = new_values[:-2] + ")"
            new_list.append(new_values)

        command = command + "VALUES " + ", ".join(new_list)
        return command

    def execute_command(self, command):
        if self.verbose is True:
            print(command)

        self.cursor.execute(command)

        ret_val = None
        if not "INSERT" in command:
            ret_val = self.cursor.fetchone()

        self.cursor.commit()

        return ret_val