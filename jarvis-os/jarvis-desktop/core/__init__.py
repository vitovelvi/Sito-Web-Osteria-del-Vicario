"""Nucleo non visivo di J.A.R.V.I.S.

Contiene cio' che non dipende dall'interfaccia: bus degli eventi, stato globale,
configurazione, identita', capability, contratto di protocollo, registry dei
servizi. Nessun modulo di questo pacchetto importa da :mod:`ui`.

E' la regola di dipendenza che tiene in piedi l'architettura: il nucleo puo'
essere usato senza GUI (test, strumenti da riga di comando, backend simulato),
mentre la GUI non puo' esistere senza il nucleo.
"""
