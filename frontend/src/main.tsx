import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import Landing from "./pages/Landing";
import "./styles/index.css";

// Two-page split without a router dependency: the marketing landing lives at "/",
// the working dashboard at "/app". Vite's SPA fallback serves index.html for both.
const isApp = window.location.pathname.startsWith("/app");

createRoot(document.getElementById("root")!).render(
  <StrictMode>{isApp ? <App /> : <Landing />}</StrictMode>,
);
