#%%
from utils import HierarchicalGridIndex

#%%
hgi = HierarchicalGridIndex(cell_size=10.0)  
    
# Point to cell  
cell = hgi.point_to_cell(25.3, 17.8, level=2)  
print(f"Cell: {cell}")  
    
# Cell to point  
center = hgi.cell_to_point(cell)  
print(f"Center: {center}")  
    
# Cell to boundary  
boundary = hgi.cell_to_boundary(cell)  
print(f"Boundary: {boundary}")  
    
# Hierarchy operations  
parent = hgi.cell_to_parent(cell, parent_level=1)  
print(f"Parent: {parent}")  
    
children = hgi.cell_to_children(parent, child_level=3)  
print(f"Number of children: {len(children)}")
# %%

hgi._get_i(cell)
# %%
hgi._get_j(cell)
# %%
