# Spiegazione modifiche — README pubblico

Questo file spiega perché è stato modificato `README.md` e cosa guardare durante una review.

## Obiettivo

Il README era corretto tecnicamente, ma conteneva dettagli troppo specifici per un repository pubblico o condiviso:

- nomi utente/account;
- hostname o domini reali;
- percorsi assoluti del server;
- riferimenti a configurazioni operative personali;
- esempi di comandi troppo vicini al deploy reale;
- dettagli che potevano far capire l'infrastruttura privata.

L'obiettivo della modifica è rendere il README più anonimo e più adatto a GitHub, mantenendo però comprensibile cosa fa Jarvis Core.

## Cosa è cambiato

### 1. Descrizione più generale

Il progetto viene presentato come un MCP server local-first per un vault Markdown sincronizzato, senza legarlo a una persona, a un server specifico o a un dominio reale.

### 2. Rimozione di dettagli identificativi

Sono stati sostituiti con esempi generici:

- percorsi reali del server;
- nomi account;
- domini pubblici;
- riferimenti a proxy specifici;
- percorsi di token e segreti usati in produzione.

Esempio del nuovo stile:

```text
/path/outside/repository/mcp-token
```

invece di un percorso reale del server.

### 3. Struttura più leggibile

Il README ora è organizzato per aree:

- cosa fornisce Jarvis Core;
- principi di sicurezza;
- gruppi di tool MCP;
- policy model;
- workflow delle capture;
- HTTP transport;
- dashboard/status page;
- watcher deterministico;
- safety contract;
- test locali;
- runtime paths.

### 4. Chiarimento su watcher e AI

Il README ora chiarisce che:

- il watcher non usa AI;
- il watcher non organizza semanticamente le note;
- crea capture `pending` solo quando le regole lo permettono;
- le decisioni ambigue restano da revisionare.

Questo è importante perché il sistema deve restare utilizzabile anche senza un modello AI disponibile.

### 5. Segreti fuori dal repository

È stato ribadito che token, password, TOTP secret, percorsi reali e dettagli di deploy devono stare fuori da Git.

## Cosa controllare in review

Chi legge dovrebbe verificare soprattutto:

1. che non siano rimasti nomi personali, host reali o percorsi privati;
2. che il README spieghi ancora bene il progetto;
3. che gli esempi siano generici ma tecnicamente utili;
4. che non vengano promesse funzionalità non presenti;
5. che la distinzione tra watcher, capture e organizzazione manuale sia chiara.

## Cosa non è stato cambiato

Questa modifica è solo documentale:

- non cambia codice Python;
- non cambia configurazioni PM2;
- non cambia policy Jarvis;
- non cambia il watcher;
- non cambia MCP;
- non cambia Syncthing;
- non cambia il vault.

## Nota per lavori futuri

Quando si aggiunge codice nuovo, conviene affiancare sempre un file di spiegazione simile a questo, così una persona esterna può capire velocemente:

- qual era il problema;
- quali file sono stati toccati;
- cosa fa il nuovo codice;
- quali limiti o rischi restano;
- quali test sono stati eseguiti.
