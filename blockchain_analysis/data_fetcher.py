"""
On-Chain Data Fetcher Module

Provides functionality to fetch various on-chain data from Ethereum/EVM networks.
"""

from web3 import Web3


class OnChainDataFetcher:
    """
    Fetches on-chain data using a BlockchainConnector instance.
    
    Attributes:
        connector: BlockchainConnector instance for blockchain access
    """
    
    def __init__(self, connector):
        """
        Initialize the OnChainDataFetcher.
        
        Args:
            connector: BlockchainConnector instance
        """
        self.connector = connector
    
    def get_block_details(self, block_number):
        """
        Retrieve details about a specific block.
        
        Args:
            block_number (int): The block number to fetch
            
        Returns:
            dict: Block details including:
                - timestamp: Block timestamp (Unix timestamp)
                - miner: Address of the block miner
                - transaction_count: Number of transactions in the block
                
        Raises:
            RuntimeError: If not connected to blockchain
        """
        if not self.connector.is_connected():
            raise RuntimeError("Not connected to blockchain. Call connect() first.")
        
        block = self.connector.w3.eth.get_block(block_number)
        
        return {
            'timestamp': block['timestamp'],
            'miner': block['miner'],
            'transaction_count': len(block['transactions'])
        }
    
    def get_native_balance(self, address):
        """
        Get the native token (ETH) balance of a wallet address.
        
        Args:
            address (str): Ethereum wallet address
            
        Returns:
            dict: Balance information including:
                - wei: Balance in Wei (smallest unit)
                - ether: Balance in Ether (formatted)
                
        Raises:
            RuntimeError: If not connected to blockchain
            ValueError: If address is invalid
        """
        if not self.connector.is_connected():
            raise RuntimeError("Not connected to blockchain. Call connect() first.")
        
        if not Web3.is_address(address):
            raise ValueError(f"Invalid Ethereum address: {address}")
        
        balance_wei = self.connector.w3.eth.get_balance(address)
        balance_ether = Web3.from_wei(balance_wei, 'ether')
        
        return {
            'wei': balance_wei,
            'ether': float(balance_ether)
        }
    
    def get_gas_price(self):
        """
        Get the current gas price from the network.
        
        Returns:
            dict: Gas price information including:
                - wei: Gas price in Wei
                - gwei: Gas price in Gwei (formatted)
                
        Raises:
            RuntimeError: If not connected to blockchain
        """
        if not self.connector.is_connected():
            raise RuntimeError("Not connected to blockchain. Call connect() first.")
        
        gas_price_wei = self.connector.w3.eth.gas_price
        gas_price_gwei = Web3.from_wei(gas_price_wei, 'gwei')
        
        return {
            'wei': gas_price_wei,
            'gwei': float(gas_price_gwei)
        }
