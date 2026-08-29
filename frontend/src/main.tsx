import { StrictMode, Suspense, lazy } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Landing from "./pages/Landing";
import "./styles/index.css";

// Docs is lazy. Its content module is ~89 KB of prose, and importing it eagerly put all of
// that into the main bundle - so every visitor to the landing page downloaded the entire
// manual before seeing a heat map. Split out, it is fetched only by the reader who asks for
// it. App and Landing stay eager: they are the two pages a first visit actually lands on.
const Docs = lazy(() => import("./pages/Docs"));

// Three pages without a router dependency: the landing at "/", the working dashboard at
// "/app", the documentation at "/docs". Vite's SPA fallback serves index.html for all of
// them, and nginx does the same in production.
//
// /docs used to be FastAPI's Swagger UI. That moved to /api/docs when this page took the
// path: an API reference and a product manual are different documents for different readers,
// and the reader who types /docs is almost never after OpenAPI.
const path = window.location.pathname;
const page = path.startsWith("/app") ? (
  <App />
) : path.startsWith("/docs") ? (
  <Suspense
    fallback={
      <div className="grid min-h-screen place-items-center bg-[#05070b] text-[13px] text-slate-600">
        Loading documentation...
      </div>
    }
  >
    <Docs />
  </Suspense>
) : (
  <Landing />
);

// One index.html serves all three routes, so every tab, bookmark and shared link carried the
// landing page's title - /app and /docs were indistinguishable from / and from each other. The
// document title is the only per-route metadata a client-rendered SPA can correct after load;
// og: tags are read by scrapers before any JS runs and stay as the site-level defaults.
document.title = path.startsWith("/app")
  ? "Cryonav Dashboard - live thermal routing"
  : path.startsWith("/docs")
    ? "Cryonav Docs - data, physics and API"
    : "Cryonav - Thermal Navigation";

createRoot(document.getElementById("root")!).render(<StrictMode>{page}</StrictMode>);
