const isMobile =
  typeof globalThis === "undefined" ? false : globalThis.innerWidth < 640;

const config = {
  geoCodingApi: "https://nominatim.openstreetmap.org",
  routingApi: "https://router.project-osrm.org/route/v1",
  mapConfig: {
    center: [-83.374_968_005_434_64, 33.938_867_465_175_66],
    zoom: isMobile ? 17 : 18.5,
    bearing: 60,
    pitch: 40,
    maxBounds: [
      [-83.388_312_312_217_47, 33.936_756_496_779_94],
      [-83.363_637_640_834_63, 33.954_777_298_795_16],
    ],
  } as maplibregl.MapOptions,
  mapStyles: {
    light: "https://tiles.openfreemap.org/styles/bright",
    dark: "/styles/dark/style.json",
  },
};

export default config;
