"""
Test suite for the Blockchain Analysis Module

Tests the blockchain connector, data fetcher, and placeholder classes
using mocked Web3 provider to avoid real network requests.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from web3 import Web3

import sys
import os

# Add the parent directory to the path to import the blockchain_analysis module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from blockchain_analysis.connector import BlockchainConnector
from blockchain_analysis.data_fetcher import OnChainDataFetcher
from blockchain_analysis.mempool import MempoolMonitor
from blockchain_analysis.mev_detector import MEVDetector


class TestBlockchainConnector(unittest.TestCase):
    """Test cases for BlockchainConnector class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.test_rpc_url = "http://test-rpc.example.com"
    
    def test_init_with_custom_rpc_url(self):
        """Test initialization with custom RPC URL"""
        connector = BlockchainConnector(rpc_url=self.test_rpc_url)
        self.assertEqual(connector.rpc_url, self.test_rpc_url)
        self.assertIsNone(connector.w3)
    
    def test_init_with_default_rpc_url(self):
        """Test initialization with default RPC URL"""
        with patch.dict(os.environ, {}, clear=True):
            connector = BlockchainConnector()
            self.assertEqual(connector.rpc_url, 'https://eth.llamarpc.com')
    
    def test_init_with_env_variable(self):
        """Test initialization with environment variable"""
        test_env_url = "http://env-rpc.example.com"
        with patch.dict(os.environ, {'ETHEREUM_RPC_URL': test_env_url}):
            connector = BlockchainConnector()
            self.assertEqual(connector.rpc_url, test_env_url)
    
    @patch('blockchain_analysis.connector.Web3')
    def test_connect_success(self, mock_web3_class):
        """Test successful connection to blockchain"""
        # Mock Web3 instance
        mock_w3_instance = MagicMock()
        mock_w3_instance.is_connected.return_value = True
        mock_web3_class.return_value = mock_w3_instance
        
        connector = BlockchainConnector(rpc_url=self.test_rpc_url)
        result = connector.connect()
        
        self.assertTrue(result)
        self.assertIsNotNone(connector.w3)
        mock_web3_class.assert_called_once()
    
    @patch('blockchain_analysis.connector.Web3')
    def test_connect_failure(self, mock_web3_class):
        """Test failed connection to blockchain"""
        # Mock Web3 to raise exception
        mock_web3_class.side_effect = Exception("Connection error")
        
        connector = BlockchainConnector(rpc_url=self.test_rpc_url)
        result = connector.connect()
        
        self.assertFalse(result)
    
    def test_is_connected_when_not_connected(self):
        """Test is_connected returns False when w3 is None"""
        connector = BlockchainConnector(rpc_url=self.test_rpc_url)
        self.assertFalse(connector.is_connected())
    
    @patch('blockchain_analysis.connector.Web3')
    def test_is_connected_when_connected(self, mock_web3_class):
        """Test is_connected returns True when connected"""
        mock_w3_instance = MagicMock()
        mock_w3_instance.is_connected.return_value = True
        mock_web3_class.return_value = mock_w3_instance
        
        connector = BlockchainConnector(rpc_url=self.test_rpc_url)
        connector.connect()
        
        self.assertTrue(connector.is_connected())
    
    @patch('blockchain_analysis.connector.Web3')
    def test_get_latest_block_number_success(self, mock_web3_class):
        """Test getting latest block number"""
        mock_w3_instance = MagicMock()
        mock_w3_instance.is_connected.return_value = True
        mock_w3_instance.eth.block_number = 12345678
        mock_web3_class.return_value = mock_w3_instance
        
        connector = BlockchainConnector(rpc_url=self.test_rpc_url)
        connector.connect()
        block_number = connector.get_latest_block_number()
        
        self.assertEqual(block_number, 12345678)
    
    def test_get_latest_block_number_not_connected(self):
        """Test getting block number when not connected raises error"""
        connector = BlockchainConnector(rpc_url=self.test_rpc_url)
        
        with self.assertRaises(RuntimeError) as context:
            connector.get_latest_block_number()
        
        self.assertIn("Not connected", str(context.exception))


class TestOnChainDataFetcher(unittest.TestCase):
    """Test cases for OnChainDataFetcher class"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_connector = Mock()
        self.mock_w3 = MagicMock()
        self.mock_connector.w3 = self.mock_w3
        self.fetcher = OnChainDataFetcher(self.mock_connector)
    
    def test_get_block_details_success(self):
        """Test getting block details"""
        self.mock_connector.is_connected.return_value = True
        
        # Mock block data
        mock_block = {
            'timestamp': 1640000000,
            'miner': '0x1234567890abcdef1234567890abcdef12345678',
            'transactions': ['tx1', 'tx2', 'tx3']
        }
        self.mock_w3.eth.get_block.return_value = mock_block
        
        result = self.fetcher.get_block_details(12345)
        
        self.assertEqual(result['timestamp'], 1640000000)
        self.assertEqual(result['miner'], '0x1234567890abcdef1234567890abcdef12345678')
        self.assertEqual(result['transaction_count'], 3)
        self.mock_w3.eth.get_block.assert_called_once_with(12345)
    
    def test_get_block_details_not_connected(self):
        """Test getting block details when not connected raises error"""
        self.mock_connector.is_connected.return_value = False
        
        with self.assertRaises(RuntimeError) as context:
            self.fetcher.get_block_details(12345)
        
        self.assertIn("Not connected", str(context.exception))
    
    @patch('blockchain_analysis.data_fetcher.Web3.from_wei')
    @patch('blockchain_analysis.data_fetcher.Web3.is_address')
    def test_get_native_balance_success(self, mock_is_address, mock_from_wei):
        """Test getting native balance"""
        self.mock_connector.is_connected.return_value = True
        mock_is_address.return_value = True
        
        test_address = '0x1234567890abcdef1234567890abcdef12345678'
        balance_wei = 1000000000000000000  # 1 ETH in Wei
        balance_ether = 1.0
        
        self.mock_w3.eth.get_balance.return_value = balance_wei
        mock_from_wei.return_value = balance_ether
        
        result = self.fetcher.get_native_balance(test_address)
        
        self.assertEqual(result['wei'], balance_wei)
        self.assertEqual(result['ether'], balance_ether)
        mock_is_address.assert_called_once_with(test_address)
        self.mock_w3.eth.get_balance.assert_called_once_with(test_address)
        mock_from_wei.assert_called_once_with(balance_wei, 'ether')
    
    def test_get_native_balance_not_connected(self):
        """Test getting balance when not connected raises error"""
        self.mock_connector.is_connected.return_value = False
        
        with self.assertRaises(RuntimeError) as context:
            self.fetcher.get_native_balance('0x1234567890abcdef1234567890abcdef12345678')
        
        self.assertIn("Not connected", str(context.exception))
    
    @patch('blockchain_analysis.data_fetcher.Web3.is_address')
    def test_get_native_balance_invalid_address(self, mock_is_address):
        """Test getting balance with invalid address raises error"""
        self.mock_connector.is_connected.return_value = True
        mock_is_address.return_value = False
        
        with self.assertRaises(ValueError) as context:
            self.fetcher.get_native_balance('invalid_address')
        
        self.assertIn("Invalid Ethereum address", str(context.exception))
    
    @patch('blockchain_analysis.data_fetcher.Web3.from_wei')
    def test_get_gas_price_success(self, mock_from_wei):
        """Test getting gas price"""
        self.mock_connector.is_connected.return_value = True
        
        gas_price_wei = 50000000000  # 50 Gwei in Wei
        gas_price_gwei = 50.0
        
        self.mock_w3.eth.gas_price = gas_price_wei
        mock_from_wei.return_value = gas_price_gwei
        
        result = self.fetcher.get_gas_price()
        
        self.assertEqual(result['wei'], gas_price_wei)
        self.assertEqual(result['gwei'], gas_price_gwei)
        mock_from_wei.assert_called_once_with(gas_price_wei, 'gwei')
    
    def test_get_gas_price_not_connected(self):
        """Test getting gas price when not connected raises error"""
        self.mock_connector.is_connected.return_value = False
        
        with self.assertRaises(RuntimeError) as context:
            self.fetcher.get_gas_price()
        
        self.assertIn("Not connected", str(context.exception))


class TestMempoolMonitor(unittest.TestCase):
    """Test cases for MempoolMonitor placeholder class"""
    
    def test_init(self):
        """Test MempoolMonitor initialization"""
        monitor = MempoolMonitor()
        self.assertIsNone(monitor.connector)
        
        mock_connector = Mock()
        monitor_with_connector = MempoolMonitor(connector=mock_connector)
        self.assertEqual(monitor_with_connector.connector, mock_connector)
    
    def test_start_monitoring_not_implemented(self):
        """Test that start_monitoring raises NotImplementedError"""
        monitor = MempoolMonitor()
        
        with self.assertRaises(NotImplementedError) as context:
            monitor.start_monitoring()
        
        self.assertIn("not yet implemented", str(context.exception))


class TestMEVDetector(unittest.TestCase):
    """Test cases for MEVDetector placeholder class"""
    
    def test_init(self):
        """Test MEVDetector initialization"""
        detector = MEVDetector()
        self.assertIsNone(detector.connector)
        
        mock_connector = Mock()
        detector_with_connector = MEVDetector(connector=mock_connector)
        self.assertEqual(detector_with_connector.connector, mock_connector)
    
    def test_detect_arbitrage_not_implemented(self):
        """Test that detect_arbitrage raises NotImplementedError"""
        detector = MEVDetector()
        
        with self.assertRaises(NotImplementedError) as context:
            detector.detect_arbitrage()
        
        self.assertIn("not yet implemented", str(context.exception))


if __name__ == '__main__':
    unittest.main()
