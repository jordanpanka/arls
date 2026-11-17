import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField } from "@mui/material";
import { useState } from "preact/hooks";

type cpProps = {
    open: boolean,
    setOpen: (b: boolean) => void
}

export function ChangePassword(props: cpProps) {
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState("");
    const [success, setSuccess] = useState(false);
    const [saving, setSaving] = useState(false);

    function close() {
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setError("");
        setSuccess(false);
        props.setOpen(false);
    }

    async function save() {
        setError("");
        if (newPassword !== confirmPassword) {
            setError("Az új jelszó és a megerősítés nem egyezik.");
            return;
        }
        setSaving(true);
        try {
            const token = localStorage.getItem("token");
            const response = await fetch("/api/auth/change-password", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token
                },
                body: JSON.stringify({ currentPassword, newPassword })
            });
            if (!response.ok) {
                setError((await response.text()) || "Nem sikerült a jelszó módosítása.");
                return;
            }
            setSuccess(true);
        } catch {
            setError("Nem sikerült a jelszó módosítása.");
        } finally {
            setSaving(false);
        }
    }

    return (
        <Dialog open={props.open} onClose={close} fullWidth maxWidth="xs">
            <DialogTitle>Jelszó módosítása</DialogTitle>
            <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, pt: "8px !important" }}>
                {success ? (
                    <Alert severity="success">A jelszó sikeresen módosult.</Alert>
                ) : (
                    <>
                        <TextField type="password" label="Jelenlegi jelszó" value={currentPassword} onChange={e => setCurrentPassword(e.currentTarget.value)} autoComplete="current-password" />
                        <TextField type="password" label="Új jelszó" value={newPassword} onChange={e => setNewPassword(e.currentTarget.value)} autoComplete="new-password" helperText="Legalább 6 karakter, kis- és nagybetűvel" />
                        <TextField type="password" label="Új jelszó megerősítése" value={confirmPassword} onChange={e => setConfirmPassword(e.currentTarget.value)} autoComplete="new-password" />
                        {error && <Alert severity="error" sx={{ whiteSpace: "pre-line" }}>{error}</Alert>}
                    </>
                )}
            </DialogContent>
            <DialogActions>
                {success ? (
                    <Button onClick={close}>Bezárás</Button>
                ) : (
                    <>
                        <Button onClick={close}>Mégse</Button>
                        <Button onClick={save} disabled={saving || !currentPassword || !newPassword || !confirmPassword}>Mentés</Button>
                    </>
                )}
            </DialogActions>
        </Dialog>
    );
}
