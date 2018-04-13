// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.
// See the LICENSE file in the project root for more information.

using System;
using System.Runtime.InteropServices;

Type argIterator = typeof(object).Assembly.GetType("System.ArgIterator");

class ArgIteratorSimple
{
    static bool ArgListSimpleTest(string s, ArgIterator va_list)
    {
        int[] expectedValues = { 100, 299, -100, 50 };
        bool result = true;

        int index = 0;
        while (va_list.GetRemainingCount() != 0) {
            TypedReference receivedReference = va_list.GetNextArg();

            int expectedValue = expectedValues[index++];
            int receivedValue = __refValue(receivedReference, Int);

            if (expectedValue != receivedValue) {
                result = false;
            }
        }

        return result;
    }

    static void Main(string[] args)
    {
        bool passed = ArgListSimpleTest("%d %d", __arglist(100, 299, -100, 50));

        return passed ? 100 : -1;
    }
}