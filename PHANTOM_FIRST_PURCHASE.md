# Primeira compra manual no Phantom — Losbeto v16

## Objetivo
Fazer a primeira compra real sem depender de valores de US$0.001. O fluxo recomendado usa **US$1 em USDC na rede Solana** e valida o nó com uma transação que cabe no seu limite mínimo de compra no Phantom.

## Passo a passo
1. Abra a Phantom e troque/compre **pelo menos US$1 em USDC na rede Solana**.
2. Garanta também um pouco de **SOL para taxas**. Sem SOL, a Phantom não envia nem faz swap.
3. Use **uma wallet diferente da wallet do node** para não misturar operação comercial com carteira de recebimento.
4. Faça um envio de **US$0.10 ou US$1.00 em USDC** para o endereço Solana do Losbeto: `GEhr9HCFTRDjanMg435frSgCVwVZYpNoPrEkmNBnFHFE`.
5. Copie a assinatura da transação (tx signature / hash) no explorer ou no histórico da Phantom.
6. Envie essa assinatura para o endpoint de bootstrap: `POST https://losbeto-production-dd7c.up.railway.app/bootstrap-trust` com o header `X-PAYMENT: <assinatura-ou-payload>`.
7. Repita até ter **3 transações reais**; isso ajuda o trust score no x402scan.
8. Depois execute a compra humana premium em `GET /starter-pack` para validar o ticket de **US$1**.

## Sugestão prática
- Compra mínima na Phantom: **US$1** em USDC.
- Teste de trust score: **3 x US$0.10**.
- Teste premium humano: **1 x US$1.00** no `/starter-pack`.

## Observações
- O serviço recebe em Solana e Base, mas o teste manual mais simples é **Solana + Phantom + USDC**.
- O endereço Base para agentes EVM é `0xd5Ba9711a3D052846a3695C70e7fcb8b3168FE7d`.
- O manifest x402 está em `https://losbeto-production-dd7c.up.railway.app/.well-known/x402.json`.
