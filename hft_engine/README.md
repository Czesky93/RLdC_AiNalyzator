# HFT Engine

A high-performance C++ order book implementation for high-frequency trading (HFT) systems.

## Overview

This is a proof-of-concept implementation of an order book with the following features:

- **Order Management**: Add and cancel orders with unique IDs
- **Price Levels**: Maintain sorted buy (bid) and sell (ask) orders
- **Best Price Queries**: Efficiently retrieve the best bid and ask prices
- **C++17**: Modern C++ implementation with standard containers

## Components

- **Order**: Struct representing a trading order (id, price, quantity, side)
- **OrderBook**: Class managing buy and sell orders with efficient price-sorted storage
- **Main Demo**: Example usage showing order book operations

## Building

### Prerequisites

- CMake 3.10 or higher
- C++17 compatible compiler (GCC 7+, Clang 5+, MSVC 2017+)

### Build Instructions

```bash
mkdir build
cd build
cmake ..
make
```

This will create the `hft_core` executable in the build directory.

### Running

After building, run the demo:

```bash
./hft_core
```

The demo will:
1. Initialize an empty order book
2. Add several buy and sell orders
3. Display the best bid and ask prices
4. Cancel orders and show updated prices

## Implementation Details

- **Data Structure**: Uses `std::map` for price-level organization
  - Bids are sorted in descending order (highest price first)
  - Asks are sorted in ascending order (lowest price first)
- **Time Complexity**:
  - Add order: O(log n)
  - Cancel order: O(log n)
  - Get best bid/ask: O(1)
- **Thread Safety**: Not currently thread-safe (future enhancement)

## Future Enhancements

- Order matching engine
- Thread-safe operations for concurrent access
- Market data feeds integration
- Performance optimizations for ultra-low latency
- Order execution and fill tracking
