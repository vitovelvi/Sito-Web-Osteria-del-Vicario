# examples

Riferimenti eseguibili per chi implementa un backend JCP.

`minimal-backend/` conterrà il server più piccolo che supera i sei punti di
conformità (§10 della specifica): handshake, capability, ping/pong, tolleranza
ai messaggi sconosciuti, stream generici, prefisso `ext.`.

Nel frattempo il riferimento eseguibile completo è
`jarvis-desktop/network/mock/backend.py`, che implementa JCP 1.0 per intero —
livello operativo incluso — ed è ciò contro cui girano i test di integrazione.
