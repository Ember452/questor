import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import "./styles/tokens.css";

const root = document.getElementById("root");
if (!root) throw new Error("Questor web root is missing");
createRoot(root).render(<App />);
