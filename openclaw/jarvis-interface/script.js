import { JarvisAgent } from './jarvis-agent.js';

document.addEventListener('DOMContentLoaded', () => {
    const listeningStatus = document.getElementById('listening-status');
    const transcriptDisplay = document.getElementById('transcript-display');
    const jarvisResponseDisplay = document.getElementById('jarvis-response-display');
    const jarvisCircle = document.querySelector('.jarvis-circle');

    let recognition; // Variabile per il riconoscimento vocale
    let isListening = false; // Stato del microfono
    let isSpeaking = false; // Jarvis sta parlando
    let isProcessing = false; // L'agente sta elaborando: il microfono deve restare fermo

    // L'agente vive sul gateway OpenClaw: stesso agente e stesso modello Gemini
    // che risponde su Telegram. La voce ElevenLabs è configurata lato gateway
    // (messages.tts), così la chiave API non passa dal browser.
    const jarvis = new JarvisAgent({
        url: 'ws://127.0.0.1:18789',
        sessionKey: 'jarvis-interface',
        speak: false, // la riproduzione la gestiamo qui, per coordinarla col microfono
        // token: '...',    // solo se gateway.auth.mode è "token"
        // password: '...', // solo se gateway.auth.mode è "password"
    });

    // Funzione per aggiornare lo stato di ascolto
    function setListeningStatus(message, color = '#00ff00') {
        listeningStatus.textContent = message;
        listeningStatus.style.color = color;
    }

    // Funzione per visualizzare il testo trascritto dall'utente
    function setTranscriptDisplay(message) {
        transcriptDisplay.textContent = message;
    }

    // Funzione per visualizzare la risposta di Jarvis
    function setJarvisResponseDisplay(message) {
        jarvisResponseDisplay.textContent = message;
    }

    // Riproduce l'audio TTS generato dal gateway con la voce Jarvis
    async function speak(text) {
        if (!text || !text.trim()) {
            riprendiAscolto();
            return;
        }

        stopVoiceRecognition(); // il microfono deve essere spento prima di parlare
        isSpeaking = true;

        try {
            const audioUrl = await jarvis.synthesize(text);
            const audio = new Audio(audioUrl);

            setJarvisResponseDisplay('Jarvis: ' + text);

            audio.onended = () => {
                isSpeaking = false;
                riprendiAscolto();
            };
            audio.onerror = () => {
                isSpeaking = false;
                riprendiAscolto();
            };

            // L'autoplay può essere bloccato finché l'utente non interagisce con
            // la pagina: non è fatale, il testo resta comunque a schermo.
            await audio.play().catch((err) => {
                console.warn('Riproduzione bloccata dal browser:', err);
                isSpeaking = false;
                riprendiAscolto();
            });
        } catch (error) {
            console.error('Errore durante la sintesi vocale:', error);
            setJarvisResponseDisplay('Jarvis: ' + text);
            setListeningStatus('Voce non disponibile (controlla messages.tts nel gateway).', 'orange');
            isSpeaking = false;
            riprendiAscolto();
        }
    }

    // Riprende l'ascolto solo se nessun'altra fase è in corso
    function riprendiAscolto() {
        if (!isListening && !isSpeaking && !isProcessing) {
            startVoiceRecognition();
        }
    }

    // Inizializza il riconoscimento vocale (Web Speech API)
    function initVoiceRecognition() {
        if (!('webkitSpeechRecognition' in window)) {
            setListeningStatus('Riconoscimento vocale non supportato dal tuo browser.', 'red');
            return;
        }

        recognition = new webkitSpeechRecognition();
        recognition.continuous = false; // CRUCIALE: processa un comando alla volta
        recognition.interimResults = true; // Mostra risultati provvisori
        recognition.lang = 'it-IT'; // Lingua italiana

        recognition.onstart = () => {
            isListening = true;
            setListeningStatus('In ascolto...', '#00ff00');
            jarvisCircle.classList.add('listening-active');
        };

        recognition.onresult = (event) => {
            let interimTranscript = '';
            let finalTranscript = '';

            for (let i = event.resultIndex; i < event.results.length; ++i) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript;
                } else {
                    interimTranscript += transcript;
                }
            }
            setTranscriptDisplay(finalTranscript || interimTranscript);

            if (finalTranscript) {
                stopVoiceRecognition(); // Ferma l'ascolto per processare il comando
                processUserCommand(finalTranscript);
            }
        };

        recognition.onend = () => {
            isListening = false;
            jarvisCircle.classList.remove('listening-active');
            // Non riavviare mentre Jarvis parla o mentre l'agente sta rispondendo:
            // una risposta reale richiede secondi e il microfono raccoglierebbe
            // rumore o la voce di Jarvis stesso.
            if (!isSpeaking && !isProcessing) {
                setListeningStatus('In pausa.', 'orange');
                setTimeout(riprendiAscolto, 1000);
            }
        };

        recognition.onerror = (event) => {
            console.error('Errore di riconoscimento vocale:', event.error);
            isListening = false;
            jarvisCircle.classList.remove('listening-active');

            if (event.error !== 'no-speech' && event.error !== 'audio-capture') {
                setListeningStatus(`Errore: ${event.error}`, 'red');
            }
            if (event.error !== 'audio-capture' && !isSpeaking && !isProcessing) {
                setTimeout(riprendiAscolto, 1000);
            }
        };
    }

    // Avvia il riconoscimento vocale
    function startVoiceRecognition() {
        if (recognition && !isListening && !isSpeaking && !isProcessing) {
            try {
                setTranscriptDisplay('');
                // La risposta resta a schermo finché non arriva un nuovo comando,
                // altrimenti sparirebbe appena Jarvis finisce di parlare.
                recognition.start();
            } catch (e) {
                if (e.message.includes('already started')) {
                    console.warn("Riconoscimento vocale già avviato, ignoro l'avvio duplicato.");
                    isListening = true;
                    setListeningStatus('In ascolto...', '#00ff00');
                    jarvisCircle.classList.add('listening-active');
                } else {
                    console.error("Errore sconosciuto durante l'avvio del riconoscimento:", e);
                }
            }
        }
    }

    // Arresta il riconoscimento vocale
    function stopVoiceRecognition() {
        if (recognition && isListening) {
            recognition.stop();
            isListening = false;
        }
    }

    // --- Invia il comando all'agente sul gateway e riceve la risposta reale ---
    async function processUserCommand(command) {
        isProcessing = true;
        setJarvisResponseDisplay('Jarvis: Elaborazione comando...');

        try {
            // chat.send è non bloccante: il testo arriva in streaming sugli
            // eventi chat, quindi la risposta compare mentre viene generata.
            const risposta = await jarvis.ask(command, {
                onDelta: (testoParziale) => setJarvisResponseDisplay('Jarvis: ' + testoParziale),
            });

            isProcessing = false;
            await speak(risposta);
        } catch (error) {
            console.error('Errore nel processare il comando utente:', error);
            isProcessing = false;
            await speak('Si è verificato un errore nella comunicazione con il gateway.');
        }
    }

    // --- Connessione al gateway OpenClaw ---
    jarvis.onStatus(({ state }) => {
        if (state === 'connecting') setListeningStatus('Connessione al gateway...', '#00c4ff');
        if (state === 'reconnecting') setListeningStatus('Riconnessione al gateway...', 'orange');
        if (state === 'disconnected') setListeningStatus('Disconnesso dal gateway.', 'red');
    });

    initVoiceRecognition();

    jarvis
        .connect()
        .then(() => {
            console.log('Connesso al gateway OpenClaw');
            setListeningStatus('Connesso. In attesa dei comandi.', '#00c4ff');
            // Il benvenuto riavvia l'ascolto quando ha finito di parlare.
            return speak('Benvenuto Signore, sono Jarvis. In attesa dei Suoi comandi.');
        })
        .catch((error) => {
            console.error('Connessione al gateway fallita:', error);
            setListeningStatus('Gateway non raggiungibile. Vedi la console.', 'red');
            setJarvisResponseDisplay('Jarvis: ' + error.message);
        });
});
