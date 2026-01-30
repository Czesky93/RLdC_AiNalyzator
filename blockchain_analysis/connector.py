"""
Blockchain Connector Module

Provides connection management to Ethereum/EVM blockchain networks.
"""

import os
from web3 import Web3


class BlockchainConnector:
    """
    Manages connection to Ethereum/EVM blockchain networks via RPC.
    
    Attributes:
        rpc_url (str): The RPC endpoint URL
        w3 (Web3): Web3 instance for blockchain interaction
    """
    
    def __init__(self, rpc_url=None):
        """
        Initialize the BlockchainConnector.
        
        Args:
            rpc_url (str, optional): RPC endpoint URL. If not provided,
                                    defaults to environment variable ETHEREUM_RPC_URL
                                    or a public Ethereum endpoint.
        """
        if rpc_url is None:
            # Try to get from environment variable, otherwise use default
            rpc_url = os.getenv('ETHEREUM_RPC_URL', 'https://eth.llamarpc.com')
        
        self.rpc_url = rpc_url
        self.w3 = None
    
    def connect(self):
        """
        Establish connection to the blockchain network.
        
        Returns:
            bool: True if connection successful, False otherwise
        """
        try:
            self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            return self.is_connected()
        except Exception as e:
            print(f"Connection failed: {e}")
            return False
    
    def is_connected(self):
        """
        Check if the connector is currently connected to the blockchain.
        
        Returns:
            bool: True if connected, False otherwise
        """
        if self.w3 is None:
            return False
        
        try:
            return self.w3.is_connected()
        except Exception:
            return False
    
    def get_latest_block_number(self):
        """
        Fetch the current block height from the blockchain.
        
        Returns:
            int: The latest block number
            
        Raises:
            RuntimeError: If not connected to the blockchain
        """
        if not self.is_connected():
            raise RuntimeError("Not connected to blockchain. Call connect() first.")
        
        return self.w3.eth.block_number
