# Neuron Steering

Neuron steering nudges individual MLP neurons while a model generates. It is an
interpretability toy: no weights change and nothing is written to disk, so
turning it off restores the model on the next load. oMLX ships no presets.

Enable it per model under **Model settings → Advanced Settings → Neuron
Steering**, enter the steering ops, and save. The engine reloads to apply or
remove the change.

## Steering ops

One op per line or comma-separated:

```
layer:neuron:value[:mode]
```

Fields can be separated by colons or spaces, and `layer` / `neuron` may carry
an `L` / `N` prefix, so `23:4769:0.8` and `L23 N4769 +0.8` are the same op.

- `layer` is the decoder layer index and `neuron` the index into the MLP
  intermediate `h = silu(gate(x)) * up(x)` that feeds `down_proj`.
- `value` is required and may be negative; `mode` defaults to `scaled`.
- `scaled` (default) adds `value * ||h_token|| / ||W_down[:, neuron]||`, a dose
  that follows the token's activation norm and the neuron's write strength.
- `constant` pins `h[..., neuron] = value` on every token. It is stronger and
  breaks coherence sooner.

For example, `L23 N4769 0.8` on Qwen3.8-27B rewords answers without changing
their content, and `16:1000:2` on Llama 3.1 8B changes the wording, while
`16:1000:30:constant, 20:2000:8` makes it degenerate. Start small. Neuron
indices are model-specific.

A malformed spec is rejected on save. An op whose layer or neuron is out of
range is skipped with a warning in the server log.

## Scope

- Works on SwiGLU decoder layers that expose `mlp.down_proj`, in both the LLM
  and VLM engines (Llama, Qwen3, Qwen3.5 and similar). Other architectures are
  left unchanged.
- Quantized `down_proj` layers are supported; the parameter tree is untouched.
- The prefix cache is keyed by the active steering ops, so KV computed with
  steering never serves an unsteered request or a different spec, and the
  other way round.

## Admin API

`PUT /admin/api/models/{model_id}/settings` accepts `neuron_steering_enabled`
(bool) and `neuron_steering_spec` (string). An invalid spec returns 400.
