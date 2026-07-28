# tools

Utilità di sviluppo per l'ecosistema JCP.

Al momento il posto è predisposto ma vuoto: gli strumenti previsti sono un
validatore di conformità (`jcp-validate`, che esegue i sei punti di §10 della
specifica contro un backend reale) e un server JCP autonomo basato sul backend
simulato già presente in `jarvis-desktop/network/mock/`.

Restano da scrivere perché finora il backend simulato è servito da dentro i
test, dove è più comodo. Diventano utili quando ci sarà un backend esterno da
verificare.
