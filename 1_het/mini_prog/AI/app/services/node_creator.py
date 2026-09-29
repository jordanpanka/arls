import os
from fastapi import UploadFile
from tree_sitter import Parser as TSParser
from tree_sitter_languages import get_language
from llama_index.core.schema import TextNode
from app.services.ollama_call import call_llm
from app.services.parse_service import CodeParser

class NodeCreator:   

    def split_code_semantically_o(self,code: str,max_chars: int = 5000,overlap: int = 300) -> list[str]:
        if len(code) <= max_chars:
            return [code]

        # 1. Próbáljunk üres sorok mentén bontani
        blocks = code.split("\n\n")

        chunks = []
        current = ""

        for block in blocks:
            candidate = current + "\n\n" + block if current else block

            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)

                if len(block) <= max_chars:
                    current = block
                else:
                    # 2. Ha egy blokk is túl hosszú, sorok alapján bontjuk
                    line_chunks = self.split_code_by_lines(block, max_chars, overlap)
                    chunks.extend(line_chunks)
                    current = ""

        if current:
            chunks.append(current)

        return chunks 
    def split_code_by_lines_o(self, code: str,max_chars: int = 5000,overlap: int = 300) -> list[str]:
        lines = code.splitlines(keepends=True)

        chunks = []
        current = ""

        for line in lines:
            if len(current) + len(line) <= max_chars:
                current += line
            else:
                if current:
                    chunks.append(current)

                # overlap az előző chunk végéből
                overlap_text = current[-overlap:] if current else ""
                current = overlap_text + line

        if current:
            chunks.append(current)

        return chunks 
    def split_code_semantically(self, code: str, max_chars: int = 2000, overlap: int = 200) -> list[str]:
        if len(code) <= max_chars:
            return [code]

        blocks = code.split("\n\n")
        chunks = []
        current = ""

        for block in blocks:
            candidate = current + "\n\n" + block if current else block

            if len(candidate) <= max_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)

                if len(block) <= max_chars:
                    current = block
                else:
                    chunks.extend(self.split_code_by_lines(block, max_chars, overlap))
                    current = ""

        if current:
            chunks.append(current)

        return chunks


    def split_code_by_lines(self, code: str, max_chars: int = 2000, overlap: int = 200) -> list[str]:
        lines = code.splitlines(keepends=True)
        chunks = []
        current = ""

        for line in lines:
            # ha egyetlen sor is túl hosszú, karakter alapján tovább daraboljuk
            if len(line) > max_chars:
                if current:
                    chunks.append(current)
                    current = ""

                for i in range(0, len(line), max_chars - overlap):
                    chunks.append(line[i:i + max_chars])
                continue

            if len(current) + len(line) <= max_chars:
                current += line
            else:
                if current:
                    chunks.append(current)

                overlap_text = current[-overlap:] if current else ""
                current = overlap_text + line

        if current:
            chunks.append(current)

        return chunks
    
    
    def ts_node_to_llamaindex_node_class_o(self,ts_node,source_code: bytes,  path:str):
            code = source_code[ts_node.start_byte:ts_node.end_byte].decode("utf-8", errors="replace")
            parse_service = CodeParser()
            class_name = parse_service.get_node_name(ts_node, source_code)
            
            return TextNode(
            text=code,
            metadata={
                "path": path,
                "kind": "class",
                "name": class_name,
                "start_line": ts_node.start_point[0] + 1,
                "start_col": ts_node.start_point[1],
                "end_line": ts_node.end_point[0] + 1,
                "end_col": ts_node.end_point[1],
                "ts_type": ts_node.type,
            }
        )
    def extract_docstring(self, body_node, source_code: bytes) -> str:
        """A torzs elso utasitasa, ha az egy string literal (Python docstring).

        Mas nyelveknel ures stringet ad vissza -- ott a vaz a fejlecbol es a
        szignaturakbol all ossze, docstring nelkul.
        """
        for child in body_node.children:
            if child.type == "comment":
                continue
            if child.type == "expression_statement":
                for sub in child.children:
                    if sub.type == "string":
                        text = source_code[sub.start_byte:sub.end_byte].decode(
                            "utf-8", errors="replace"
                        ).strip()
                        # Csak az elso sor: a vaznak rovidnek kell maradnia.
                        return text.splitlines()[0][:200] if text else ""
            # Az elso erdemi utasitas utan mar nem johet docstring.
            break
        return ""

    def class_skeleton(self, ts_node, source_code: bytes, function_types: list) -> str:
        """Az osztaly interfesze: fejlec + docstring + metodus-szignaturak.

        A teljes torzs helyett ezt foglaltatjuk ossze az LLM-mel. Egy nagy
        osztaly igy nem esik szet 14 chunkra (a Bill_App 23587 karakter volt),
        es az osszefoglalo tenylegesen az osztaly egeszerol szol, nem egy
        veletlen kodtoredekrol.

        A metodustorzsek nem vesznek el: azok kulon function node-kent
        indexelodnek. Ma ugyanazok a torzsek ketszer szerepelnek -- az osztaly
        chunkjaiban es sajat node-kent is.
        """
        body = ts_node.child_by_field_name("body")
        if body is None:
            # Ismeretlen grammatika: marad a mai viselkedes, a teljes torzs.
            return source_code[ts_node.start_byte:ts_node.end_byte].decode(
                "utf-8", errors="replace"
            )

        # "class Bill_App(Frame):" -- a node elejetol a torzs elejeig
        header = source_code[ts_node.start_byte:body.start_byte].decode(
            "utf-8", errors="replace"
        ).strip()

        lines = [header]

        docstring = self.extract_docstring(body, source_code)
        if docstring:
            lines.append("    " + docstring)

        for child in body.children:
            if child.type not in function_types:
                continue
            method_body = child.child_by_field_name("body")
            end = method_body.start_byte if method_body else child.end_byte
            signature = source_code[child.start_byte:end].decode(
                "utf-8", errors="replace"
            ).strip()
            lines.append("    " + signature + " ...")

        return "\n".join(lines)

    def ts_node_to_llamaindex_node_class(
    self,
    ts_node,
    source_code: bytes,
    path: str
) -> list[TextNode]:

        parse_service = CodeParser()
        class_name = parse_service.get_node_name(ts_node, source_code)

        # A nyelvhez tartozo fuggveny-node tipusok, hogy a metodusokat
        # felismerjuk a torzsben. A code_parsers-bol jon, tehat nyelvenkent
        # automatikusan a helyes ertek (function_definition, method_declaration...).
        try:
            parse_service.select_language(path)
            function_types = parse_service.code_parsers[
                parse_service.selected_language
            ]["node_types"]["function"]
        except (KeyError, IndexError):
            function_types = []

        code = self.class_skeleton(ts_node, source_code, function_types)

        # A vaz gyakorlatilag mindig elfer egy darabban; a chunkolas csak
        # biztonsagi halo egy szelsosegesen sok metodusu osztalyra.
        chunks = self.split_code_semantically(code)

        nodes = []

        for index, chunk in enumerate(chunks, start=1):
            nodes.append(
                TextNode(
                    text=chunk,
                    metadata={
                        "path": path,
                        "kind": "class",
                        "name": class_name,
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "is_chunked": len(chunks) > 1,
                        "start_line": ts_node.start_point[0] + 1,
                        "start_col": ts_node.start_point[1],
                        "end_line": ts_node.end_point[0] + 1,
                        "end_col": ts_node.end_point[1],
                        "ts_type": ts_node.type,
                    }
                )
            )

        return nodes
    def ts_node_to_llamaindex_node_function_o(self, ts_node, source_code:bytes,  path:str):
        code = source_code[ts_node.start_byte:ts_node.end_byte].decode("utf-8", errors="replace")
        parse_service=CodeParser()
        return TextNode(
        text=code,
        metadata={
            "path": path,
            "kind": "function",
            "name": parse_service.get_node_name(ts_node, source_code),
            "start_line": ts_node.start_point[0] + 1,
            "start_col": ts_node.start_point[1],
            "end_line": ts_node.end_point[0] + 1,
            "end_col": ts_node.end_point[1],
            "ts_type": ts_node.type,
        })
    def ts_node_to_llamaindex_node_function(
    self,
    ts_node,
    source_code: bytes,
    path: str
) -> list[TextNode]:

        code = source_code[ts_node.start_byte:ts_node.end_byte].decode(
            "utf-8",
            errors="replace"
        )

        parse_service = CodeParser()
        function_name = parse_service.get_node_name(ts_node, source_code)

        chunks = self.split_code_semantically(code)

        nodes = []

        for index, chunk in enumerate(chunks, start=1):
            nodes.append(
                TextNode(
                    text=chunk,
                    metadata={
                        "path": path,
                        "kind": "function",
                        "name": function_name,
                        "chunk_index": index,
                        "chunk_count": len(chunks),
                        "is_chunked": len(chunks) > 1,
                        "start_line": ts_node.start_point[0] + 1,
                        "start_col": ts_node.start_point[1],
                        "end_line": ts_node.end_point[0] + 1,
                        "end_col": ts_node.end_point[1],
                        "ts_type": ts_node.type,
                    }
                )
            )

        return nodes
    async def generate_summary_to_node(self,node)->str:
            code = node.text
            path = node.metadata.get("path", "")
            kind = node.metadata.get("kind", "")
            name = node.metadata.get("name", "")

            # Az osszefoglalok MINDIG angolul keszulnek, fuggetlenul attol, hogy a
            # felhasznalo milyen nyelven kerdez kesobb. Egy nyelven tartva oket a
            # summary-vektorok egy szemantikus terben maradnak: egy magyar kerdes
            # angolra forditva keresi oket, igy nem a nyelv, hanem a tartalom dont.
            # Korabban a modell a hivasok ketharmadaban angolul, egyharmadaban
            # magyarul valaszolt, ami ketteszakitotta ezt a teret.
            prompt = f"""
            Summarise in at most 3 sentences what this {kind} does: what its main
            responsibility is, and what its most important methods or behaviour are.
            Be technical and concise.

            Always answer in English, no matter what language the code, its comments
            or its identifiers are written in.
            Do not use headings, bullet points or Markdown formatting (**, #, -).
            Do not quote the code back. Do not start with "This code..." or anything
            similar - start directly with what it does.

            Name: {name}
            Path: {path}

            Code:
            {code}

            Summary:
            """
            
            summary = await call_llm(prompt)

            # IDEIGLENESEN KIVÉVE: a check_summary node-onként megduplázta az
            # LLM-hívások számát, a visszakapott százalékot viszont csak
            # kiírtuk, sehol nem használtuk. Egy CPU-n futó llama3-nál ez
            # önmagában kétszeresére nyújtotta az import idejét.
            # A metódus alább megmarad; visszakapcsoláshoz elég ez a két sor:
            # perc=await self.check_summary(code,summary.strip())
            # print(" A százalékos mgfeleltság" +perc)

            return summary.strip()
        
    async def check_summary(self, code, summary)->float:
        prompt=f"""
        Feladat:
        Ellenőrizd le, hogy az adott kódhoz tartozó összefoglaló megfelel- e annak amit az adott kód tartalmaz. 
        
        Mateadatok:
        -Kód:{code}
        -Összefoglaló:{summary}
        
        A válasz egy szám legyen,  az alapján hogy hány százalékban felel meg az összefoglaló a kódnak.
        """
        perc=await call_llm(prompt)
        return perc.strip()
        
        
    