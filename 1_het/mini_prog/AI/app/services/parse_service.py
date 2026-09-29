import os
from fastapi import UploadFile
from tree_sitter import Parser as TSParser
from tree_sitter_languages import get_language
from llama_index.core.schema import TextNode
from app.services.ollama_call import call_llm

class CodeParser:
    
    def __init__(self):
        self.selected_language = None
    
    '''code_parsers = {
        ".c": get_language("c"),
        ".cs": get_language("c_sharp"),
        ".py": get_language("python"),
        ".js": get_language("javascript"),
        ".ts": get_language("typescript"),
        ".tsx": get_language("tsx"),
        ".jsx": get_language("javascript"),
        ".java": get_language("java"),
        ".go": get_language("go"),
        ".rs": get_language("rust"),
        ".php": get_language("php"),
        ".cpp": get_language("cpp"),
    }'''
    code_parsers = {
    ".py": {
        "language": get_language("python"),
        "name": "python",
        "node_types": {
            "class": ["class_definition"],
            "function": ["function_definition"],
            "call": ["call"],
            "import": ["import_statement", "import_from_statement"]
        }
    },

    ".cs": {
        "language": get_language("c_sharp"),
        "name": "c_sharp",
        "node_types": {
            "class": ["class_declaration"],
            "function": ["method_declaration"],
            "call": ["invocation_expression"],
            "import": ["using_directive"]
        }
    },

    ".js": {
        "language": get_language("javascript"),
        "name": "javascript",
        "node_types": {
            "class": ["class_declaration"],
            "function": ["function_declaration", "method_definition"],
            "call": ["call_expression"],
            "import": ["import_statement"]
        }
    },

    ".ts": {
        "language": get_language("typescript"),
        "name": "typescript",
        "node_types": {
            "class": ["class_declaration"],
            "function": ["function_declaration", "method_definition"],
            "call": ["call_expression"],
            "import": ["import_statement"]
        }
    },

    ".tsx": {
        "language": get_language("tsx"),
        "name": "typescript",
        "node_types": {
            "class": ["class_declaration"],
            "function": ["function_declaration", "method_definition"],
            "call": ["call_expression"],
            "import": ["import_statement"]
        }
    },
    ".java": {
        "language": get_language("java"),
        "name": "java",
        "node_types": {
            "class": ["class_declaration"],
            "function": ["method_declaration"],
            "call": ["method_invocation"],
            "import": ["import_declaration"]
        }
    },
    ".jsx": {
    "language": get_language("javascript"),
    "name": "javascript",
    "node_types": {
        "class": ["class_declaration"],
        "function": ["function_declaration", "method_definition"],
        "call": ["call_expression"],
        "import": ["import_statement"]
    }
},

    ".php": {
        "language": get_language("php"),
        "name": "php",
        "node_types": {
            "class": ["class_declaration", "interface_declaration", "trait_declaration", "enum_declaration"],
            "function": ["function_definition", "method_declaration"],
            "call": [
                "function_call_expression", "member_call_expression",
                "scoped_call_expression", "nullsafe_member_call_expression",
                "object_creation_expression"
            ],
            # A require/include is ugyanugy fuggoseg, mint a use.
            "import": [
                "namespace_use_declaration", "require_expression", "require_once_expression",
                "include_expression", "include_once_expression"
            ]
        }
    },

    ".go": {
        "language": get_language("go"),
        "name": "go",
        # A type_declaration csak burkolo, a nev a type_spec-en van, ezert az
        # utobbi az "osztaly". A metodusok a Go-ban a tipuson kivul allnak,
        # igy fuggvenykent indexelodnek, nem a struct metodusaikent.
        "node_types": {
            "class": ["type_spec"],
            "function": ["function_declaration", "method_declaration"],
            "call": ["call_expression"],
            "import": ["import_declaration"]
        }
    },

    ".rs": {
        "language": get_language("rust"),
        "name": "rust",
        # Az impl_item is "osztaly": a metodusok a torzseben ulnek, enelkul
        # nem allna ossze az osztaly-metodus kapcsolat.
        "node_types": {
            "class": ["struct_item", "enum_item", "trait_item", "impl_item"],
            "function": ["function_item"],
            "call": ["call_expression"],
            "import": ["use_declaration", "extern_crate_declaration"]
        }
    },

    ".c": {
        "language": get_language("c"),
        "name": "c",
        "node_types": {
            "class": ["struct_specifier", "union_specifier", "enum_specifier"],
            "function": ["function_definition"],
            "call": ["call_expression"],
            "import": ["preproc_include"]
        }
    },

    ".cpp": {
        "language": get_language("cpp"),
        "name": "cpp",
        "node_types": {
            "class": ["class_specifier", "struct_specifier", "union_specifier", "enum_specifier"],
            "function": ["function_definition"],
            "call": ["call_expression"],
            "import": ["preproc_include", "using_declaration"]
        }
    }
}

    # A .h lehet C es C++ is; a cpp grammatika mindkettot elparszolja, a c nem.
    code_parsers[".hpp"] = code_parsers[".cpp"]
    code_parsers[".h"] = code_parsers[".cpp"]

    # Egy deklaracio nevet hordozo node-tipusok a tamogatott nyelveken. A PHP
    # "name"-et hasznal, a Rust/C++ tipusdeklaraciok "type_identifier"-t, a Go
    # metodusok es a C++ tagfuggvenyek "field_identifier"-t.
    name_node_types = [
        "identifier", "property_identifier", "name",
        "type_identifier", "field_identifier", "qualified_identifier"
    ]

    def select_language(self, file_path:str)->str:
        # Kisbetusitve: a .PY es a .Cs ugyanaz a nyelv, mint a .py es a .cs.
        ext = os.path.splitext(file_path)[1].lower()
        self.selected_language=ext
        config=self.code_parsers.get(ext)
        # Indexeles helyett .get(): igy a hivo ValueError-aga fut le, nem egy
        # nyers KeyError szall fel az API-ig.
        return config["language"] if config else None

    async def parse_code_to_tree(self,file:UploadFile, path:str):
        
        source_code=await file.read()
        parser=TSParser()
        config=self.select_language(path)
        if config is None:
            raise ValueError(f"Unsupported file type: {path}")
        parser.set_language(config)
        tree=parser.parse(source_code)
        return tree, source_code
    
    def extract_class_function_nodes(self,node):
        classes=[]
        functions=[]
        #JAVITAS: minden függvényt 2x tárol el vagy csak egyszer és a külsö függvényeket külön
        node_types=self.code_parsers[self.selected_language]["node_types"]
        if(node.type in node_types["class"]):
            classes.append(node)
        
        elif(node.type in node_types["function"]):
            functions.append(node)
        for child in node.children:
            child_classes, child_functions = self.extract_class_function_nodes(child)

            classes.extend(child_classes)
            functions.extend(child_functions)

        return classes, functions
    
    def node_text(self, ts_node, source_code: bytes) -> str:
        return source_code[ts_node.start_byte:ts_node.end_byte].decode(
            "utf-8",
            errors="replace"
        )

    def get_node_name(self, ts_node, source_code: bytes) -> str | None:
        # A legtobb grammatika megcimkezi a deklaracio nevet, es a cimke
        # megbizhatobb, mint a gyerekek sorrendje.
        named = ts_node.child_by_field_name("name")
        if named is not None:
            return self.node_text(named, source_code)

        # A C es a C++ egy-ket szinttel lejjebb, a declaratorban tartja a nevet:
        # function_definition -> function_declarator -> identifier.
        declarator = ts_node.child_by_field_name("declarator")
        while declarator is not None:
            if declarator.type in self.name_node_types:
                return self.node_text(declarator, source_code)
            declarator = declarator.child_by_field_name("declarator")

        # Nev-mezo nelkuli deklaraciok (pl. a Rust impl_item "type" mezoje).
        for child in ts_node.children:
            if child.type in self.name_node_types:
                return self.node_text(child, source_code)

        return None
        
    def print_tree(self, node, indent=0):
        print("  " * indent + f"{node.type} [{node.start_point} - {node.end_point}]")
        
        for child in node.children:
            self.print_tree(child, indent + 1)
            
    def extract_imports(self, node, source_code: bytes) -> list[str]:
        imports = []

        node_types = self.code_parsers[self.selected_language]["node_types"]

        if node.type in node_types["import"]:
            import_text = source_code[node.start_byte:node.end_byte].decode(
                "utf-8",
                errors="replace"
            )
            imports.append(import_text)

        for child in node.children:
            imports.extend(self.extract_imports(child, source_code))

        return imports
    
    def extract_calls_from_function(self, function_node, source_code: bytes) -> list[str]:
        calls = []

        node_types = self.code_parsers[self.selected_language]["node_types"]

        def walk(node):
            if node.type in node_types["call"]:
                function_child = node.child_by_field_name("function")

                if function_child is None and len(node.children) > 0:
                    function_child = node.children[0]

                if function_child is not None:
                    call_name = source_code[
                        function_child.start_byte:function_child.end_byte
                    ].decode("utf-8", errors="replace")

                    calls.append(call_name)

            for child in node.children:
                walk(child)

        walk(function_node)
        return calls
    def extract_methods_in_classes(self, class_nodes, source_code: bytes) -> list[dict]:
        relations = []

        for class_node in class_nodes:
            class_name = self.get_node_name(class_node, source_code)

            for child in class_node.children:
                child_classes, child_functions = self.extract_class_function_nodes(child)

                for fn in child_functions:
                    method_name = self.get_node_name(fn, source_code)

                    if class_name and method_name:
                        relations.append({
                            "class": class_name,
                            "method": method_name,
                            "start_line": fn.start_point[0] + 1,
                            "end_line": fn.end_point[0] + 1
                        })

        return relations
    
    def extract_graph_relations(self, tree, source_code: bytes) -> dict:
        imports = self.extract_imports(tree.root_node, source_code)

        _, functions = self.extract_class_function_nodes(tree.root_node)

        classes, functions = self.extract_class_function_nodes(tree.root_node)

        methods = self.extract_methods_in_classes(classes, source_code)
        calls = []

        for fn in functions:
            caller_name = self.get_node_name(fn, source_code)

            if caller_name is None:
                continue

            called_functions = self.extract_calls_from_function(fn, source_code)

            for called_name in called_functions:
                calls.append({
                    "caller": caller_name,
                    "called": called_name,
                    "caller_start_line": fn.start_point[0] + 1,
                    "caller_end_line": fn.end_point[0] + 1
                })
            

        return {
                "imports": imports,
                "calls": calls,
                "methods": methods
            }
      