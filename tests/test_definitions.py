import unittest

from src.definitions.search import (
    answer_definition_question,
    answer_definition_question_json,
    split_dataset_name,
)


class DefinitionSearchTests(unittest.TestCase):
    def test_definition_intent_international_student(self):
        answer = answer_definition_question("wat is een internationale student?")

        self.assertIn("Een student wordt als internationale student beschouwd", answer)
        self.assertIn("Indicatie internationale student", answer)
        self.assertIn("Indicatie internationale student op peildatum 1 oktober", answer)

    def test_location_intent_international_student(self):
        answer = answer_definition_question("waar vind ik data over internationale studenten?")

        self.assertIn("Je vindt data over internationale studenten", answer)
        self.assertIn("Inschrijvingen_aggr_UNL_2025.csv", answer)
        self.assertIn("Diplomas_aggr_UNL_2025.csv", answer)
        self.assertIn("EOIcohort_UNL_2025.csv", answer)
        self.assertIn("EOIcohort_21P*_2025.csv", answer)

    def test_dataset_splitting_keeps_source_labels(self):
        split_eoi = split_dataset_name("EOIcohort_UNL_2025.csv / EOIcohort_21P*_2025.csv")
        self.assertIn("EOIcohort_UNL_2025.csv", split_eoi)
        self.assertIn("EOIcohort_21P*_2025.csv", split_eoi)
        self.assertEqual(2, len(split_eoi))

        source_label = split_dataset_name("VH informatieproducten / 1cijferHO")
        self.assertEqual(["VH informatieproducten / 1cijferHO"], source_label)
        self.assertNotIn("VH informatieproducten", source_label)
        self.assertNotIn("1cijferHO", source_label)

    def test_student_definition(self):
        answer = answer_definition_question("wat telt als student?")

        self.assertIn("student/ingeschrevene", answer)
        self.assertIn("persoonsgebonden nummer", answer)
        self.assertIn("inschrijvingsrecord", answer)

    def test_json_output(self):
        result = answer_definition_question_json("waar vind ik data over internationale studenten?")

        self.assertIsInstance(result, dict)
        self.assertEqual("location", result["intent"])
        self.assertEqual("Internationale student", result["main_term"])
        self.assertIsInstance(result["datasets"], list)
        self.assertIsInstance(result["fields"], list)


if __name__ == "__main__":
    unittest.main()
