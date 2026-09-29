import '../styles/login.css'
import avatar from "../assets/avatar.png";
import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';

export function Login() {
    const [register, setRegister] = useState(false);
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [firstName, setFirstName] = useState("");
    const [lastName, setLastName] = useState("");
    const { route } = useLocation();
    async function onClick() {
        if (register) {
            const r = await fetch("api/auth/register", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(
                    {
                        email, password, firstName, lastName
                    }
                )
            });
            if (!r.ok) {
                const data = await r.text();
                alert(data);
                return;
            }
            setRegister(false);

        }
        else {
            const nothing = "";
            const nothing2 = "";
            const r = await fetch("api/auth/login", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    email, password, firstName, lastName
                })
            });
            if (!r.ok) {
                const data = await r.text();
                alert(data);
                return;
            }
            const data = await r.json();
            console.log("LOGIN DATA:", data);
            console.log("TOKEN TYPE:", typeof data.token);
            console.log("TOKEN RAW:", data.token);
            console.log("TOKEN PARTS:", data.token?.split("."));
            console.log("TOKEN PART COUNT:", data.token?.split(".")?.length);
            localStorage.setItem("token", data.token);
            setFirstName(data.firstName);
            setLastName(data.lastName);

            route("/chat", true);

        }
    }

    return <div className="login-container">
        <div className="login-card">
            <div className="avatar">
                <img src={avatar} alt="Avatar"></img>
            </div>
            {register && <>
                <input value={firstName} placeholder="First name" onInput={e => setFirstName(e.currentTarget.value)}></input>
                <input value={lastName} placeholder="Last name" onInput={e => setLastName(e.currentTarget.value)}></input>
            </>}
            <input type="email" value={email} placeholder="Email address" onInput={e => setEmail(e.currentTarget.value)}></input>
            <input type="password" value={password} placeholder="Password" onInput={e => setPassword(e.currentTarget.value)}></input>
            <button className="login-btn" onClick={onClick} >{register ? "Register" : "Login"}</button>
            {!register && <p>Have no account yet? <a href="" onClick={(e) => { e.preventDefault(); setRegister(true); }}>Register</a></p>}

        </div>
    </div>
}