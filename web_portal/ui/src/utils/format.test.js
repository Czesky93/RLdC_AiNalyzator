import { formatCurrency, formatPercentage } from './format';

describe('formatCurrency', () => {
  test('formats positive numbers correctly', () => {
    expect(formatCurrency(1234.56)).toBe('$1,234.56');
  });

  test('formats negative numbers correctly', () => {
    expect(formatCurrency(-1234.56)).toBe('-$1,234.56');
  });

  test('formats zero correctly', () => {
    expect(formatCurrency(0)).toBe('$0.00');
  });

  test('handles large numbers with proper comma separation', () => {
    expect(formatCurrency(1234567.89)).toBe('$1,234,567.89');
  });

  test('handles null values', () => {
    expect(formatCurrency(null)).toBe('$0.00');
  });

  test('handles undefined values', () => {
    expect(formatCurrency(undefined)).toBe('$0.00');
  });

  test('handles NaN values', () => {
    expect(formatCurrency(NaN)).toBe('$0.00');
  });
});

describe('formatPercentage', () => {
  test('formats decimal as percentage correctly', () => {
    expect(formatPercentage(0.68)).toBe('68.00%');
  });

  test('formats zero correctly', () => {
    expect(formatPercentage(0)).toBe('0.00%');
  });

  test('formats 100% correctly', () => {
    expect(formatPercentage(1)).toBe('100.00%');
  });

  test('formats negative percentages correctly', () => {
    expect(formatPercentage(-0.15)).toBe('-15.00%');
  });

  test('handles null values', () => {
    expect(formatPercentage(null)).toBe('0.00%');
  });

  test('handles undefined values', () => {
    expect(formatPercentage(undefined)).toBe('0.00%');
  });

  test('handles NaN values', () => {
    expect(formatPercentage(NaN)).toBe('0.00%');
  });
});
