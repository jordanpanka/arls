import { render } from "preact";
import "./styles/index.css";
import { App } from "./pages/app";
import { OpenWindow } from "./components/upload/openWindow";

render(<OpenWindow />, document.getElementById('app')!)
