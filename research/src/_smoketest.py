import numpy, scipy, sklearn, matplotlib, anndata, scanpy, squidpy, ot, paste, torch, torch_geometric

print("numpy           ", numpy.__version__)
print("scipy           ", scipy.__version__)
print("torch           ", torch.__version__, "| cuda?", torch.cuda.is_available())
print("torch_geometric ", torch_geometric.__version__)
print("anndata         ", anndata.__version__)
print("scanpy          ", scanpy.__version__)
print("squidpy         ", squidpy.__version__)
print("POT (ot)        ", ot.__version__)
print("paste-bio       ", getattr(paste, "__version__", "imported ok"))

# quick functional check: a tiny PyG graph + message pass
from torch_geometric.nn import GCNConv
x = torch.randn(4, 3)
edge_index = torch.tensor([[0, 1, 2, 3], [1, 0, 3, 2]], dtype=torch.long)
out = GCNConv(3, 8)(x, edge_index)
print("GCNConv output  ", tuple(out.shape))
print("ALL IMPORTS OK")
