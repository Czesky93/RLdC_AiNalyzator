#include "order_book.h"
#include <iostream>
#include <iomanip>

using namespace hft;

void printBestPrices(const OrderBook& book) {
    std::cout << std::fixed << std::setprecision(2);
    
    auto bestBid = book.getBestBid();
    auto bestAsk = book.getBestAsk();
    
    std::cout << "Best Bid: ";
    if (bestBid.has_value()) {
        std::cout << "$" << bestBid.value();
    } else {
        std::cout << "N/A";
    }
    std::cout << std::endl;
    
    std::cout << "Best Ask: ";
    if (bestAsk.has_value()) {
        std::cout << "$" << bestAsk.value();
    } else {
        std::cout << "N/A";
    }
    std::cout << std::endl;
    
    if (bestBid.has_value() && bestAsk.has_value()) {
        std::cout << "Spread: $" << (bestAsk.value() - bestBid.value()) << std::endl;
    }
    std::cout << std::endl;
}

int main() {
    std::cout << "=== HFT Engine - Order Book Demo ===" << std::endl << std::endl;
    
    OrderBook book;
    
    std::cout << "Initial state (empty order book):" << std::endl;
    printBestPrices(book);
    
    // Add some buy orders
    std::cout << "Adding buy orders..." << std::endl;
    book.addOrder(Order("B1", 100.50, 10, Side::BUY));
    book.addOrder(Order("B2", 100.25, 5, Side::BUY));
    book.addOrder(Order("B3", 100.75, 15, Side::BUY));
    printBestPrices(book);
    
    // Add some sell orders
    std::cout << "Adding sell orders..." << std::endl;
    book.addOrder(Order("S1", 101.00, 10, Side::SELL));
    book.addOrder(Order("S2", 101.25, 5, Side::SELL));
    book.addOrder(Order("S3", 100.90, 20, Side::SELL));
    printBestPrices(book);
    
    // Cancel the best bid
    std::cout << "Canceling best bid order (B3)..." << std::endl;
    book.cancelOrder("B3");
    printBestPrices(book);
    
    // Cancel the best ask
    std::cout << "Canceling best ask order (S3)..." << std::endl;
    book.cancelOrder("S3");
    printBestPrices(book);
    
    std::cout << "=== Demo Complete ===" << std::endl;
    
    return 0;
}
