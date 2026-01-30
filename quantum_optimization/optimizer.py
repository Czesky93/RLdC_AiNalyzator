"""
Quantum Portfolio Optimizer using Qiskit
Implements portfolio optimization using quantum algorithms (VQE/QAOA).
"""

import numpy as np
from qiskit_algorithms.minimum_eigensolvers import SamplingVQE, QAOA
from qiskit_algorithms.optimizers import SLSQP, COBYLA
from qiskit.circuit.library import TwoLocal
from qiskit.primitives import StatevectorSampler
from qiskit_optimization import QuadraticProgram
from qiskit_optimization.algorithms import MinimumEigenOptimizer
from qiskit_optimization.converters import QuadraticProgramToQubo


class QuantumPortfolioOptimizer:
    """
    Quantum-based portfolio optimizer using Qiskit.
    Uses VQE or QAOA to solve the portfolio optimization problem.
    """
    
    def __init__(self, algorithm='VQE'):
        """
        Initialize the quantum optimizer.
        
        Args:
            algorithm: Quantum algorithm to use ('VQE' or 'QAOA')
        """
        self.algorithm = algorithm
        print(f"Initialized Quantum Portfolio Optimizer with {algorithm}")
    
    def optimize_portfolio(self, expected_returns, covariance_matrix, budget=1, risk_factor=0.5):
        """
        Optimize portfolio allocation using quantum algorithms.
        
        Args:
            expected_returns: numpy array of expected returns for each asset
            covariance_matrix: numpy array of covariance matrix (risk)
            budget: Maximum number of assets to select (default: 1)
            risk_factor: Risk tolerance parameter (default: 0.5)
        
        Returns:
            dict: Optimization results containing:
                - selection: Binary array indicating which assets to select
                - optimal_value: The optimal portfolio value
                - weights: Normalized weights for selected assets
        """
        num_assets = len(expected_returns)
        print(f"\nOptimizing portfolio with {num_assets} assets...")
        print(f"Budget (max assets): {budget}")
        print(f"Risk factor: {risk_factor}")
        
        # Create portfolio optimization quadratic program manually
        qp = QuadraticProgram('portfolio')
        
        # Add binary variables for each asset (1 = selected, 0 = not selected)
        for i in range(num_assets):
            qp.binary_var(f'x_{i}')
        
        # Objective: Maximize return - risk_factor * risk
        # We minimize the negative (i.e., maximize): -(returns) + risk_factor * (variance)
        
        # Linear coefficients (returns - we want to maximize these)
        linear = {}
        for i in range(num_assets):
            linear[f'x_{i}'] = -expected_returns[i]  # Negative because we're minimizing
        
        # Quadratic coefficients (covariance - risk penalty)
        quadratic = {}
        for i in range(num_assets):
            for j in range(num_assets):
                if i <= j:  # Only upper triangle needed
                    key = (f'x_{i}', f'x_{j}')
                    quadratic[key] = risk_factor * covariance_matrix[i, j]
        
        qp.minimize(linear=linear, quadratic=quadratic)
        
        # Budget constraint: sum of selected assets <= budget
        constraint_linear = {f'x_{i}': 1 for i in range(num_assets)}
        qp.linear_constraint(constraint_linear, '<=', budget)
        
        print(f"Quadratic program created with {qp.get_num_vars()} variables")
        
        # Convert to QUBO format
        converter = QuadraticProgramToQubo()
        qubo = converter.convert(qp)
        
        # Setup quantum algorithm
        if self.algorithm == 'VQE':
            # Create variational form
            ansatz = TwoLocal(
                num_assets, 
                rotation_blocks='ry', 
                entanglement_blocks='cz',
                entanglement='linear',
                reps=3
            )
            
            # Create SamplingVQE instance (for optimization problems)
            optimizer = SLSQP(maxiter=100)
            vqe = SamplingVQE(
                sampler=StatevectorSampler(),
                ansatz=ansatz,
                optimizer=optimizer
            )
            
            print("Using VQE (Variational Quantum Eigensolver)...")
            quantum_instance = vqe
            
        else:  # QAOA
            # Create QAOA instance
            optimizer = COBYLA(maxiter=100)
            qaoa = QAOA(
                sampler=StatevectorSampler(),
                optimizer=optimizer,
                reps=3
            )
            
            print("Using QAOA (Quantum Approximate Optimization Algorithm)...")
            quantum_instance = qaoa
        
        # Solve using quantum algorithm with sampling-based optimizer
        print("Running quantum optimization...")
        meo = MinimumEigenOptimizer(quantum_instance)
        
        try:
            result = meo.solve(qubo)
            
            # Extract solution
            selection = np.array([int(result.x[i]) for i in range(num_assets)])
            
            print(f"\n✓ Optimization complete!")
            print(f"Selected assets: {np.sum(selection)}/{num_assets}")
            
            # Calculate weights for selected assets
            weights = self._calculate_weights(selection, expected_returns)
            
            # Calculate portfolio metrics
            portfolio_return = np.dot(weights, expected_returns)
            portfolio_risk = np.sqrt(np.dot(weights, np.dot(covariance_matrix, weights)))
            
            results = {
                'selection': selection,
                'optimal_value': float(result.fval),
                'weights': weights,
                'portfolio_return': portfolio_return,
                'portfolio_risk': portfolio_risk,
                'sharpe_ratio': portfolio_return / portfolio_risk if portfolio_risk > 0 else 0
            }
            
            return results
            
        except Exception as e:
            print(f"Error during optimization: {e}")
            raise
    
    def _calculate_weights(self, selection, expected_returns):
        """
        Calculate normalized weights for selected assets.
        Uses expected returns to weight the selected assets.
        
        Args:
            selection: Binary array of selected assets
            expected_returns: Expected returns for each asset
        
        Returns:
            numpy array of normalized weights
        """
        weights = np.zeros(len(selection))
        
        # Get indices of selected assets
        selected_indices = np.where(selection == 1)[0]
        
        if len(selected_indices) == 0:
            return weights
        
        # Weight by expected returns (higher return = higher weight)
        selected_returns = expected_returns[selected_indices]
        
        # Handle negative or zero returns
        if np.all(selected_returns <= 0):
            # Equal weight if all returns are non-positive
            weights[selected_indices] = 1.0 / len(selected_indices)
        else:
            # Normalize positive returns to sum to 1
            positive_returns = np.maximum(selected_returns, 1e-10)
            normalized_weights = positive_returns / np.sum(positive_returns)
            weights[selected_indices] = normalized_weights
        
        return weights
