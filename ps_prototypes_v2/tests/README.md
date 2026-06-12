# Unit Tests for PatchSorter

This directory contains comprehensive unit tests for all functions in the `utils.py` module and `start_v1.py`.

## Testing Approach

The tests are designed to ensure:
- All functions work correctly with their expected inputs  
- Edge cases are handled properly
- The modified `prediction_loss_pseudo` function implements the high-confidence logic as requested

## Running Tests

To run the tests, you can execute:

```bash
python3 -m pytest tests/test_utils_pytest.py -v
```

Or run individual test files directly:
```bash
python3 tests/test_utils_comprehensive.py
python3 tests/test_start_v1.py
```

## Test Coverage

### utils.py Functions Tested:
- `LabeledRateTracker` - Class for tracking label rates and weights
- `get_transforms` - Data augmentation transforms  
- `JointHead` - Neural network head with shared layers
- `repulsion_loss` - Loss function for point repulsion
- `MemoryBank` - Memory bank for storing embeddings
- `importance_score_tensor` - Score calculation for memory management
- `assign_bins` - Bin assignment for coordinates
- `get_margin` - Margin calculation for temporal loss  
- `temporal_loss` - Temporal consistency loss
- `intra_bin_repulsion_vectorized` - Intra-bin repulsion loss
- `bin_losses_vectorized` - Vectorized binning losses
- `prediction_loss_pseudo` - Main function we modified (see below)
- `semantic_head_loss` - Semantic consistency loss
- `neighborhood_loss` - Neighborhood consistency loss
- `initialize_projection_from_batch` - Projection initialization
- `SpreadLoss` - Spread loss for coordinate distribution  
- `max_mean_discrepancy` - MMD loss function
- `simclr_loss` - SimCLR contrastive loss
- `vicreg_loss` - VICReg regularization loss
- `gaussian_mask` - Gaussian masking function

### Key Function Modified: prediction_loss_pseudo 

The core functionality was updated according to your requirements:
1. Only consider patches as high-confidence if more than 50% of views agree on the same label
2. The minimum confidence threshold is >= pseudo_thresh for at least one view  
3. When patches are considered high-confidence, apply that pseudo-label to ALL views of that patch

## Test Structure

Each test function validates:
- Proper input handling and type checking
- Correct output shapes and types 
- Edge cases (empty inputs, single elements)
- Integration with other components when appropriate