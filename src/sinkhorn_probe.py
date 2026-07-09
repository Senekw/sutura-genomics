"""
One more principled attempt to close the OOD gap: replace the model's per-spot
softmax attention with a Sinkhorn (doubly-stochastic) transport plan, injecting
PASTE2's optimal-transport mass-balance structure into the learned Sutura model.
Trained with the best in-house recipe (2 donors x 2 pairs + augmentation + weight
decay + early stop), evaluated on held-out Br8100. Reuses the generalization_max
harness. LODO-honest (Br8100 never in training).
"""
from __future__ import annotations
import sys, time
import numpy as np, torch
sys.path.insert(0, "src")
import generalization_max as G
from train_cross import ARCACrossNet, graph_tensors
from scoring import registration_error_stats


class SinkhornCrossNet(ARCACrossNet):
    """Coarse correspondence via a Sinkhorn-normalized (doubly-stochastic) plan
    instead of a row-wise softmax — a differentiable soft-OT that balances the mass
    each reference spot receives, mimicking PASTE2's transport."""
    def forward(self, ga, gb, a_coords_norm, return_match=False, n_iter=3):
        z_a = self.encoder(ga["x"], ga["edge_index"], ga["edge_attr"])
        z_b = self.encoder(gb["x"], gb["edge_index"], gb["edge_attr"])
        qb, ka = self.q(z_b), self.k(z_a)
        logP = (qb @ ka.T) * self.scale
        for _ in range(n_iter):                       # Sinkhorn iterations (log domain)
            logP = logP - torch.logsumexp(logP, dim=1, keepdim=True)
            logP = logP - torch.logsumexp(logP, dim=0, keepdim=True)
        P = logP.exp()
        attn = P / (P.sum(1, keepdim=True) + 1e-9)    # row-normalize for barycentric coord
        coarse = attn @ a_coords_norm
        attended = attn @ self.v(z_a)
        residual = self.head(torch.cat([z_b, attended, coarse], dim=-1))
        pred = coarse + residual
        if not return_match:
            return pred
        qn = torch.nn.functional.normalize(qb, dim=1); kn = torch.nn.functional.normalize(ka, dim=1)
        return pred, {"attn_logits": logP, "cos_sim": qn @ kn.T}


def train_eval(held_out="Br8100"):
    cfg = G.Config("sinkhorn", n_train_donors=2, pairs_per_donor=2, augment=True,
                   weight_decay=1e-4, early_stop=True, epochs=60, steps_per_epoch=20)
    train_donors = [d for d in G.DONORS if d != held_out]
    rng = np.random.default_rng(0); torch.manual_seed(0)
    slices = [s for d in train_donors for pr in G.DONORS[d][:cfg.pairs_per_donor] for s in pr]
    basis = G.fit_fold_basis(slices, "svd", G.HP["pca_dim"], cfg.hvg_n)
    dim = basis["components"].shape[0]
    train_pairs = [G.prep_pair(pr[0], pr[1], basis, G.HP["knn"])
                   for d in train_donors for pr in G.DONORS[d][:cfg.pairs_per_donor]]
    ho = G.prep_pair(*G.DONORS[held_out][0], basis, G.HP["knn"])
    idp = G.prep_pair(*G.DONORS[train_donors[0]][0], basis, G.HP["knn"])
    model = SinkhornCrossNet(dim, G.HP["hidden"], G.HP["layers"], G.HP["attn_dim"])
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)

    def ev(p, sevs=G.EVAL_SEVS, seed=0):
        model.eval(); e = []
        for sv in sevs:
            from warp_slice import apply_warp
            w, _ = apply_warp(p["B"], sv, seed=seed, tear=True)
            gb = graph_tensors(np.asarray(w.obsm["spatial"], float), p["Z_B"], p["knn"], p["pitch"])
            with torch.no_grad():
                pred = model(p["ga"], gb, p["a_norm"]).numpy() * p["pitch"]
            e.append(registration_error_stats(pred, p["gt"], mask=p["have"])["median"] / p["pitch"])
        return float(np.mean(e))

    t0 = time.time(); best = 1e9; best_state = None; bad = 0
    for epoch in range(cfg.epochs):
        model.train()
        for _ in range(cfg.steps_per_epoch):
            p = train_pairs[int(rng.integers(len(train_pairs)))]
            sev = float(rng.uniform(0, 10.0))
            coords, Zb = G.augment_move(p, sev, rng, cfg)
            n = coords.shape[0]
            sel = np.sort(rng.choice(n, int(n*rng.uniform(0.7,1.0)), replace=False)) if (n>500 and rng.random()<0.5) else np.arange(n)
            gb = graph_tensors(coords[sel], Zb[sel], p["knn"], p["pitch"])
            opt.zero_grad()
            pred = model(p["ga"], gb, p["a_norm"])
            loss = (pred - p["gt_norm"][sel])[p["mask"][sel]].norm(dim=1).mean()
            loss.backward(); opt.step()
        if epoch % 5 == 0 or epoch == cfg.epochs-1:
            v = ev(idp, sevs=[2.0,6.0], seed=555)
            if v < best-1e-3: best=v; best_state={k:t.clone() for k,t in model.state_dict().items()}; bad=0
            else:
                bad+=1
                if bad>=4: break
            print(f"  ep{epoch:3d} val={v:.2f} held-out={ev(ho):.2f}", flush=True)
    if best_state: model.load_state_dict(best_state)
    print(f"\nSINKHORN held-out {held_out}: in-dist={ev(idp):.2f}  held-out={ev(ho):.2f} "
          f"(augment+reg softmax was 8.44 on Br8100; PASTE2 3.46)  {time.time()-t0:.0f}s")


if __name__ == "__main__":
    train_eval("Br8100")
