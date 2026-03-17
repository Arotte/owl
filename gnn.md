# Graph Neural Networks

Graph Neural Networks (GNNs) are a class of deep learning models designed to operate on **graph-structured data** — data represented as nodes (vertices) and edges (connections between them).

## Why they exist

Traditional neural networks (CNNs, RNNs, etc.) assume data lies on a regular grid (images) or a sequence (text). Many real-world datasets are naturally graphs — social networks, molecules, knowledge graphs, citation networks, road networks — and don't fit neatly into grids or sequences.

## Core idea — message passing

Most GNNs work through iterative *message passing*:

1. Each node has a feature vector (embedding).
2. In each layer, every node **aggregates** information from its neighbors (e.g., sum, mean, or attention-weighted combination of neighbor embeddings).
3. The aggregated message is combined with the node's own embedding and passed through a learned transformation (typically a linear layer + nonlinearity).
4. After *k* layers, each node's embedding encodes information from its *k*-hop neighborhood.

## Common architectures

- **GCN** (Graph Convolutional Network) — spectral-inspired, uses normalized mean aggregation.
- **GraphSAGE** — samples and aggregates neighbors, supports inductive learning on unseen nodes.
- **GAT** (Graph Attention Network) — uses attention mechanisms to weight neighbor contributions.
- **GIN** (Graph Isomorphism Network) — maximally expressive under the Weisfeiler-Leman graph isomorphism test.
- **MPNN** (Message Passing Neural Network) — a general framework that encompasses most of the above.

## Typical tasks

| Task | Example |
|---|---|
| **Node classification** | Predict a user's role in a social network |
| **Edge prediction** | Predict missing links (e.g., drug-protein interactions) |
| **Graph classification** | Predict molecular properties from a molecule's graph |
| **Graph generation** | Generate novel molecular structures |

## Key strengths

Permutation invariance/equivariance (output doesn't depend on arbitrary node ordering), ability to capture relational structure, and flexible handling of variable-size inputs.

## Key limitations

Over-smoothing with many layers (all node embeddings converge), difficulty capturing long-range dependencies, and expressiveness bounded by the WL isomorphism test (cannot distinguish certain non-isomorphic graphs).

## GNN vs Transformer — under the hood

A GNN is **not** itself a graph — the graph is the input data, not the model. The model is a stack of simple layers, similar in spirit to a transformer.

### Transformer layer (one block)

```
For each token i:
  1. Attend to ALL other tokens:  attention_scores = softmax(Q_i · K^T / √d)
  2. Aggregate:                   context_i = attention_scores · V
  3. Transform:                   output_i = FFN(LayerNorm(context_i + x_i))
```

Every token can attend to **every other token**. The connectivity is **fully connected** and **learned** via attention weights.

### GNN layer (one block)

```
For each node i:
  1. Gather neighbors:   messages = {h_j for j in neighbors(i)}
  2. Aggregate:          agg_i = AGG(messages)        # sum, mean, or attention
  3. Transform:          h_i' = MLP(concat(h_i, agg_i))
```

Each node only talks to its **graph neighbors**. The connectivity is **fixed by the input graph**.

### Side-by-side comparison

| Aspect | Transformer | GNN |
|---|---|---|
| **Input** | Sequence of tokens | Graph (nodes + edges) |
| **Connectivity** | Every token sees every token (fully connected) | Each node sees only its neighbors |
| **Who decides connectivity?** | Learned (attention weights) | The input graph (edges) |
| **Learnable parameters** | Q, K, V projections + FFN weights | Aggregation weights + MLP weights |
| **One layer captures** | Global context (any token) | 1-hop neighborhood |
| **k layers capture** | Still global (but refined) | k-hop neighborhood |
| **Positional info** | Added explicitly (positional encoding) | Implicit in graph structure |

A GNN layer has very few learnable parameters — often just a weight matrix W and sometimes attention weights (in GAT). The "intelligence" comes from the graph structure guiding information flow, not from massive parameter counts.

A useful mental model: a **transformer is a GNN on a fully connected graph** — every token is a node with edges to all others. The attention mechanism learns to *weight* those edges. A GNN on an actual graph is like a transformer where most attention weights are forced to zero (no edge = no attention).

## GNNs vs Transformers — what researchers think

### The case for GNNs on graphs

- **Inductive bias**: GNNs bake in the graph structure — they *know* only neighbors matter, requiring less data to learn local patterns.
- **Scalability**: Each node only looks at its neighbors, so GNNs scale to massive graphs (millions of nodes). All-pairs attention on a million-node graph would be intractable.
- **Sample efficiency**: When labeled data is scarce, the structural prior helps — the model doesn't waste capacity learning that distant nodes are irrelevant.

### The case for Transformers on graphs

- **Expressiveness**: GNNs are bounded by the WL isomorphism test — there are graph structures they literally *cannot distinguish*. Transformers don't have this limitation.
- **Over-smoothing**: GNNs with many layers collapse all node representations toward the same vector. Transformers handle depth much better.
- **Long-range dependencies**: A GNN needs *k* layers to propagate info *k* hops. A transformer captures global context in a single layer.
- **Graph Transformers** (e.g., Graphormer, GPS, TokenGT): These treat nodes as tokens, add positional/structural encodings (degree, random walk, Laplacian eigenvectors), and run a standard transformer. They've achieved state-of-the-art on several molecular benchmarks.

### What works best in practice

| Scenario | What works best |
|---|---|
| **Small/medium graphs** (< ~10k nodes) | Graph Transformers — all-pairs attention is feasible and more expressive |
| **Large graphs** (100k+ nodes) | GNNs or hybrid approaches — full attention doesn't scale |
| **Lots of labeled data** | Transformers — they can learn structure from data alone |
| **Little labeled data** | GNNs — the inductive bias compensates |
| **Need long-range info** | Transformers or hybrid (GNN + transformer layers) |
| **Homophilic graphs** (similar nodes connected) | GNNs work great — local aggregation matches the data |
| **Heterophilic graphs** (different nodes connected) | Transformers or specialized GNNs — naive message passing hurts |

### Summary

Neither is universally better. The trend is toward **hybrid architectures** (like GPS — General, Powerful, Scalable) that combine local message passing (GNN) with global attention (transformer) in each layer. Pure GNNs are losing ground on benchmarks where transformers can be applied, but remain essential for large-scale graphs where quadratic attention is not feasible.

Practical takeaway: if your graph fits in memory for all-pairs attention, try a Graph Transformer first. If it doesn't, use a GNN or a hybrid.
