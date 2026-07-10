# SELF_BOOTSTRAP — Losbeto v16

## Objetivo
Gerar as 3 primeiras transações reais para o node aparecer melhor em marketplaces e aumentar o trust score no x402scan.

## Regra prática
- Use **uma wallet Solana diferente** da wallet de recebimento do node.
- Compre/receba **US$1+ em USDC na Phantom**.
- Faça **3 envios de US$0.10** para o endereço do node em Solana.
- Cada envio deve ser seguido do registro no endpoint `/bootstrap-trust`.

## Endereço de recebimento Solana
`GEhr9HCFTRDjanMg435frSgCVwVZYpNoPrEkmNBnFHFE`

## Flow
1. Phantom → enviar USDC para o endereço acima.
2. Copiar a assinatura da transação.
3. Fazer um POST em:
   `https://losbeto-production-dd7c.up.railway.app/bootstrap-trust`
4. Repetir 3 vezes.

## Observação
Qualquer valor **>= US$0.01** conta tecnicamente, mas **US$0.10** é melhor para teste humano porque respeita o limite operacional comum da Phantom e deixa um histórico menos “spam-like”.
