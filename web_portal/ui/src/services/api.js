import axios from 'axios';

// Configure base URL - can be overridden via environment variable
const BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

// Create axios instance with default config
const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 10000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// API service object
const api = {
  /**
   * Get dashboard statistics (Balance, Total PnL, Win Rate)
   * @returns {Promise} Response with stats object
   */
  getDashboardStats: async () => {
    try {
      const response = await apiClient.get('/dashboard/stats');
      return response.data;
    } catch (error) {
      console.error('Error fetching dashboard stats:', error);
      throw new Error(
        error.response?.data?.message || 'Failed to fetch dashboard statistics'
      );
    }
  },

  /**
   * Get equity history for chart visualization
   * @returns {Promise} Response with equity history array
   */
  getEquityHistory: async () => {
    try {
      const response = await apiClient.get('/dashboard/equity-history');
      return response.data;
    } catch (error) {
      console.error('Error fetching equity history:', error);
      throw new Error(
        error.response?.data?.message || 'Failed to fetch equity history'
      );
    }
  },

  /**
   * Get trade history for recent trades table
   * @returns {Promise} Response with trades array
   */
  getTradeHistory: async () => {
    try {
      const response = await apiClient.get('/dashboard/trade-history');
      return response.data;
    } catch (error) {
      console.error('Error fetching trade history:', error);
      throw new Error(
        error.response?.data?.message || 'Failed to fetch trade history'
      );
    }
  },
};

export default api;
