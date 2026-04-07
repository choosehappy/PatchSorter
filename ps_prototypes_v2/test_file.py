#!/usr/bin/env python3
"""Test file for code review agent"""


def hello_world():
    print("Hello, World!")
    return "Hello, World!"


# This should trigger a linting warning
def bad_function(x, y):
    return x + y


if __name__ == "__main__":
    hello_world()
