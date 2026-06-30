export const piatti = [
  {
    slug: "macedonia-stagione",
    nome: "Macedonia frutta e verdure di stagione",
    nomeEn: "Seasonal vegetable and fruit salad",
    img: "/immagini/piatti/piatto-12.jpg",
    ingredienti: ["Verdure di stagione", "Frutta di stagione", "Erbe aromatiche"],
    allergeni: [],
    storia:
      "Un benvenuto leggero che segue il ritmo dell'orto: cambia con le stagioni, come la cucina dell'Osteria fa da sempre dal 1100.",
    vino: "Vermentino di Toscana, fresco e minerale",
  },
  {
    slug: "zucchina-cetriolo-mandorla",
    nome: "Zucchina, cetriolo, mandorla e capperi",
    nomeEn: "Courgette, cucumber, almond and capers",
    img: "/immagini/piatti/vegan.jpg",
    ingredienti: ["Zucchina", "Cetriolo", "Mandorla", "Capperi"],
    allergeni: ["Frutta a guscio (mandorla)"],
    storia:
      "Croccantezza e acidità si incontrano in un piatto vegetale pensato per aprire il palato, con la sapidità dei capperi a fare da contrappunto.",
    vino: "Vernaccia di San Gimignano",
  },
  {
    slug: "panzanella",
    nome: "Essenziale di panzanella",
    nomeEn: "Tomato, cucumber, onion, bread",
    img: "/immagini/piatti/piatto-13.jpeg",
    ingredienti: ["Pomodoro", "Cetriolo", "Cipolla", "Pane toscano"],
    allergeni: ["Glutine"],
    storia:
      "La panzanella contadina toscana, riportata all'essenziale: pane sciocco, pomodoro maturo e cipolla, senza nulla che distragga.",
    vino: "Trebbiano toscano",
  },
  {
    slug: "taco-toscano",
    nome: "Taco Toscano",
    nomeEn: "Taco, white beans, pappa al pomodoro and onions",
    img: "/immagini/piatti/piatto-03.jpeg",
    ingredienti: ["Taco", "Fagioli bianchi", "Pappa al pomodoro", "Cipolle"],
    allergeni: ["Glutine"],
    storia:
      "Un incontro fuori dagli schemi tra la pappa al pomodoro toscana e il formato del taco: tradizione contadina servita in un boccone.",
    vino: "Chianti giovane, leggermente fresco di servizio",
  },
  {
    slug: "spaghetti-spirulina-nori-salicornia",
    nome: "Spaghetti, spirulina, nori e salicornia",
    nomeEn: "Spaghetti, spirulina and salicornia seaweed",
    img: "/immagini/piatti/piatto-20.jpeg",
    ingredienti: ["Spaghetti", "Spirulina", "Alga nori", "Salicornia"],
    allergeni: ["Glutine"],
    storia:
      "Le note di mare arrivano in collina: spirulina, nori e salicornia danno profondità a uno spaghetto asciutto e sapido.",
    vino: "Vermentino della costa toscana",
  },
  {
    slug: "pasta-fresca-del-mese",
    nome: "Pasta fresca fatta a mano del mese",
    nomeEn: "Homemade handmade pasta",
    img: "/immagini/piatti/piatto-10.jpeg",
    ingredienti: ["Pasta fresca fatta a mano", "Ricetta e condimento del mese"],
    allergeni: ["Glutine", "Può contenere uova"],
    storia:
      "Ogni mese la cucina propone una pasta fresca diversa, tirata a mano secondo la stagione e l'estro del momento.",
    vino: "Da abbinare in base alla ricetta del mese: chiedi al servizio",
  },
  {
    slug: "anguria-bbq",
    nome: "Anguria BBQ, purè di patate, cipolle",
    nomeEn: "BBQ watermelon, potato puree, onions",
    img: "/immagini/piatti/piatto-04.jpeg",
    ingredienti: ["Anguria grigliata", "Purè di patate", "Cipolle caramellate"],
    allergeni: [],
    storia:
      "L'anguria grigliata sul fuoco vivo assume una consistenza quasi di carne: un gioco di affumicature su un frutto estivo.",
    vino: "Rosato toscano servito fresco",
  },
  {
    slug: "melanzana-hummus",
    nome: "Melanzana, hummus, uvetta e basilico",
    nomeEn: "Roasted eggplant, hummus, raisins and basil",
    img: "/immagini/piatti/piatto-01.webp",
    ingredienti: ["Melanzana arrostita", "Hummus di ceci", "Uvetta", "Basilico"],
    allergeni: ["Sesamo (tahin)"],
    storia:
      "Melanzana arrostita lentamente, hummus cremoso e un punto di dolcezza dall'uvetta: equilibrio mediterraneo in un piatto.",
    vino: "Bianco toscano da uve Trebbiano e Malvasia",
  },
];

export const risottoDelMese = {
  nome: "Risotto del mese",
  nomeEn: "Risotto of the month",
  ingredienti: ["Riso carnaroli", "Ricetta a rotazione mensile in base alla stagione"],
  allergeni: ["Può contenere lattosio, a seconda della ricetta del mese"],
  varianti: [
    { img: "/immagini/piatti/risotto-pesto.jpg", alt: "Risotto al pesto" },
    { img: "/immagini/piatti/piatto-risotto-viola.jpeg", alt: "Risotto viola con cipolla rossa" },
    { img: "/immagini/piatti/piatto-06.jpeg", alt: "Risotto alla zucca" },
    { img: "/immagini/piatti/piatto-07.jpeg", alt: "Risotto verde alle erbe" },
  ],
};

export const dolci = {
  nome: "Desserts",
  nomeEn: "Daily selection",
  testo: "Una selezione di dolci che cambia ogni giorno in base a cosa prepara la cucina.",
  foto: [
    { img: "/immagini/piatti/dolce.jpg", alt: "Dolce della casa" },
    { img: "/immagini/piatti/dolce-2.jpg", alt: "Dessert della casa con crumble" },
    { img: "/immagini/piatti/piatto-17.jpeg", alt: "Dessert cremoso con crumble" },
  ],
};
