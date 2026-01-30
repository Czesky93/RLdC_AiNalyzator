#include "order_book.h"

namespace hft {

void OrderBook::addOrder(const Order& order) {
    if (order.side == Side::BUY) {
        bids_[order.price].emplace(order.id, order);
    } else {
        asks_[order.price].emplace(order.id, order);
    }
    orderIndex_[order.id] = {order.price, order.side};
}

bool OrderBook::cancelOrder(const std::string& orderId) {
    auto it = orderIndex_.find(orderId);
    if (it == orderIndex_.end()) {
        return false;
    }

    double price = it->second.first;
    Side side = it->second.second;

    if (side == Side::BUY) {
        auto priceIt = bids_.find(price);
        if (priceIt != bids_.end()) {
            priceIt->second.erase(orderId);
            if (priceIt->second.empty()) {
                bids_.erase(priceIt);
            }
        }
    } else {
        auto priceIt = asks_.find(price);
        if (priceIt != asks_.end()) {
            priceIt->second.erase(orderId);
            if (priceIt->second.empty()) {
                asks_.erase(priceIt);
            }
        }
    }

    orderIndex_.erase(it);
    return true;
}

std::optional<double> OrderBook::getBestBid() const {
    if (bids_.empty()) {
        return std::nullopt;
    }
    return bids_.begin()->first;
}

std::optional<double> OrderBook::getBestAsk() const {
    if (asks_.empty()) {
        return std::nullopt;
    }
    return asks_.begin()->first;
}

} // namespace hft
