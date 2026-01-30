#ifndef ORDER_BOOK_H
#define ORDER_BOOK_H

#include <string>
#include <map>
#include <optional>

namespace hft {

enum class Side {
    BUY,
    SELL
};

struct Order {
    std::string id;
    double price;
    int quantity;
    Side side;

    Order(const std::string& id, double price, int quantity, Side side)
        : id(id), price(price), quantity(quantity), side(side) {}
};

class OrderBook {
public:
    OrderBook() = default;
    
    void addOrder(const Order& order);
    bool cancelOrder(const std::string& orderId);
    std::optional<double> getBestBid() const;
    std::optional<double> getBestAsk() const;

private:
    // Map of price -> map of order_id -> order
    // For bids: higher price is better (reverse order)
    // For asks: lower price is better (normal order)
    std::map<double, std::map<std::string, Order>, std::greater<double>> bids_;
    std::map<double, std::map<std::string, Order>> asks_;
    
    // Quick lookup: order_id -> (price, side)
    std::map<std::string, std::pair<double, Side>> orderIndex_;
};

} // namespace hft

#endif // ORDER_BOOK_H
