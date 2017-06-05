// Licensed to the .NET Foundation under one or more agreements.
// The .NET Foundation licenses this file to you under the MIT license.
// See the LICENSE file in the project root for more information.

using System;

// 10 byte struct
public struct A
{
    public int a;
    public int b;
    public short c;
}

// 32 byte struct
public struct B
{
    public long a;
    public long b;
    public long c;
    public long d;
}

public class DoNotFastTailCallWithStructs
{
    static A a;
    static B b;

    public static void Foo(B b, int count=1000)
    {
        if (count == 100)
        {
            return count;
        }

        if (count-- % 2 == 0)
        {
            return Foo(a, count);
        }

        else
        {
            return Foo(b, count);
        }
    }

    public static void Foo(A a, int count=1000)
    {
        if (count == 100)
        {
            return count;
        }

        if (count-- % 2 == 0)
        {
            return Foo(a, count);
        }

        else
        {
            return Foo(b, count);
        }
    }

    public static int Main()
    {
        a = new A();
        b = new B();

        a.a = 100;
        a.b = 1000;
        a.c = 10000;

        b.a = 500;
        b.b = 5000;
        b.c = 50000;
        b.d = 500000;

        return Foo(a);
    }
}