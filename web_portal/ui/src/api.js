import axios from "axios";

const API_URL = import.meta.env.VITE_API_URL || import.meta.env.REACT_APP_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: API_URL
});

export async function fetchSummary() {
  const { data } = await api.get("/api/summary");
  return data;
}

export async function fetchMarketSummary() {
  const { data } = await api.get("/api/market/summary");
  return data;
}

export async function fetchKlines(symbol, tf = "1h") {
  const { data } = await api.get("/api/market/kline", { params: { symbol, tf, limit: 200 } });
  return data;
}

export async function fetchDemoSummary() {
  const { data } = await api.get("/api/demo/summary");
  return data;
}

export async function fetchDemoOrders() {
  const { data } = await api.get("/api/demo/orders");
  return data;
}

export async function fetchLiveAccount() {
  const { data } = await api.get("/api/live/account");
  return data;
}

export async function fetchLiveOrders() {
  const { data } = await api.get("/api/live/orders");
  return data;
}

export async function fetchLivePositions() {
  const { data } = await api.get("/api/live/positions");
  return data;
}

export async function fetchBlog() {
  const { data } = await api.get("/api/blog");
  return data;
}

export async function fetchLogs(limit = 30) {
  const { data } = await api.get("/api/logs", { params: { limit } });
  return data;
}

export async function createDemoOrder(payload) {
  const { data } = await api.post("/api/demo/orders", payload);
  return data;
}

export async function createBlogPost(payload) {
  const { data } = await api.post("/api/blog", payload);
  return data;
}

export async function publishBlogPost(postId) {
  const { data } = await api.put(`/api/blog/${postId}/publish`);
  return data;
}

export async function deleteBlogPost(postId) {
  const { data } = await api.delete(`/api/blog/${postId}`);
  return data;
}

export async function sendTelegramAlert(message) {
  const { data } = await api.post("/api/alerts/telegram", { message });
  return data;
}
