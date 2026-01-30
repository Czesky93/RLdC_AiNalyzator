/**
 * Format a numeric value as currency (USD)
 * @param {number} value - The numeric value to format
 * @returns {string} Formatted currency string (e.g., "$1,234.56")
 */
export const formatCurrency = (value) => {
  if (value === null || value === undefined || isNaN(value)) {
    return '$0.00';
  }
  
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
};

/**
 * Format a numeric value as percentage
 * @param {number} value - The numeric value to format (e.g., 0.15 for 15%)
 * @returns {string} Formatted percentage string (e.g., "15.00%")
 */
export const formatPercentage = (value) => {
  if (value === null || value === undefined || isNaN(value)) {
    return '0.00%';
  }
  
  return new Intl.NumberFormat('en-US', {
    style: 'percent',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
};
