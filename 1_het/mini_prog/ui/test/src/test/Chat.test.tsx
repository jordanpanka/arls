import { render, screen, fireEvent } from "@testing-library/preact";
import { describe, it, expect, vi } from "vitest";

vi.mock("@mui/material", () => ({
  Box: (props: any) => <div {...props}>{props.children}</div>,
  Paper: (props: any) => <div {...props}>{props.children}</div>,
  Typography: (props: any) => <div {...props}>{props.children}</div>,
  IconButton: (props: any) => <button {...props}>{props.children}</button>,
  TextField: (props: any) => (
    <input
      placeholder={props.placeholder}
      value={props.value}
      onInput={props.onChange}
    />
  )
}));

vi.mock("@mui/icons-material/Send", () => ({
  default: () => <span>send</span>
}));

vi.stubGlobal("fetch", vi.fn(() =>
  Promise.resolve({
    json: () => Promise.resolve([])
  })
));

import { ChatWindow } from "../components/chat/Chat";

describe("ChatWindow", () => {
  it("bele lehet írni az inputba", () => {
    render(
      <ChatWindow
        newChat={false}
        setNewChat={vi.fn()}
        sellectedProjId={1}
        selectedInvId={1}
        selectedCOnversationId={1}
        setSelectedConversationId={vi.fn()}
      />
    );

    const input = screen.getByPlaceholderText("What do you want to know?");

    fireEvent.input(input, {
      target: { value: "Teszt" }
    });

    expect(input).toHaveValue("Teszt");
  });
});