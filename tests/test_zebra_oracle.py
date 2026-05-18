from __future__ import annotations

from prism.evaluation.benchmarks.zebra_oracle import solve_zebra_puzzle


def test_oracle_solves_basic_position_and_equality_puzzle():
    puzzle = """There are 2 houses, numbered 1 to 2 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Alice`, `Bob`
 - Each person has a favorite color: `red`, `blue`

## Clues:
1. Alice is in the first house.
2. Bob is the person whose favorite color is blue.
"""

    solution = solve_zebra_puzzle(puzzle)

    assert solution is not None
    assert solution["Name_Alice"] == "house1"
    assert solution["Name_Bob"] == "house2"
    assert solution["Color_blue"] == "house2"
    assert solution["Color_red"] == "house1"


def test_oracle_solves_next_to_and_directly_left_puzzle():
    puzzle = """There are 3 houses, numbered 1 to 3 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Alice`, `Bob`, `Carol`
 - The people keep unique animals: `cat`, `dog`, `fish`

## Clues:
1. Alice is in the first house.
2. The dog owner is directly left of Bob.
3. The cat lover and Carol are next to each other.
4. Bob is in the third house.
5. The cat lover is in the third house.
"""

    solution = solve_zebra_puzzle(puzzle)

    assert solution is not None
    assert solution["Name_Alice"] == "house1"
    assert solution["Name_Bob"] == "house3"
    assert solution["Animal_dog"] == "house2"
    assert solution["Name_Carol"] == "house2"
    assert solution["Animal_cat"] == "house3"


def test_oracle_returns_none_for_ambiguous_puzzle():
    puzzle = """There are 2 houses, numbered 1 to 2 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Alice`, `Bob`
 - Each person has a favorite color: `red`, `blue`

## Clues:
1. Alice is in the first house.
"""

    assert solve_zebra_puzzle(puzzle) is None


def test_oracle_solves_real_grid_mode_food_and_animal_aliases():
    puzzle = """There are 5 houses, numbered 1 to 5 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Peter`, `Alice`, `Bob`, `Eric`, `Arnold`
 - The people are of nationalities: `norwegian`, `german`, `dane`, `brit`, `swede`
 - People have unique favorite book genres: `fantasy`, `biography`, `romance`, `mystery`, `science fiction`
 - Everyone has something unique for lunch: `stir fry`, `grilled cheese`, `pizza`, `spaghetti`, `stew`
 - Each person has a favorite color: `red`, `green`, `blue`, `yellow`, `white`
 - The people keep unique animals: `bird`, `dog`, `cat`, `horse`, `fish`

## Clues:
1. The person who loves fantasy books is the Norwegian.
2. The cat lover and the person who loves biography books are next to each other.
3. The German is Bob.
4. The person who loves yellow is Bob.
5. The person whose favorite color is green is Peter.
6. There is one house between the Dane and the person who is a pizza lover.
7. The person who loves blue is somewhere to the left of the Dane.
8. The person who loves eating grilled cheese is somewhere to the left of the Norwegian.
9. The person who loves the spaghetti eater is Peter.
10. The person who keeps horses is Alice.
11. The fish enthusiast is directly left of the person who loves science fiction books.
12. There is one house between the Norwegian and Arnold.
13. The person who loves romance books is the British person.
14. There are two houses between the Norwegian and Alice.
15. The bird keeper is the person whose favorite color is red.
16. The dog owner is directly left of the fish enthusiast.
17. The person who loves the stew is the Norwegian.
"""

    solution = solve_zebra_puzzle(puzzle)

    assert solution is not None
    assert solution["Name_Bob"] == "house1"
    assert solution["Nationality_norwegian"] == "house2"
    assert solution["BookGenre_science_fiction"] == "house3"
    assert solution["Food_pizza"] == "house5"
    assert solution["Color_white"] == "house5"
    assert solution["Animal_horse"] == "house5"


def test_oracle_solves_occupation_and_phone_aliases():
    puzzle = """There are 4 houses, numbered 1 to 4 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Alice`, `Eric`, `Arnold`, `Peter`
 - Each person has an occupation: `artist`, `engineer`, `teacher`, `doctor`
 - People have unique favorite book genres: `fantasy`, `science fiction`, `mystery`, `romance`
 - People use unique phone models: `google pixel 6`, `iphone 13`, `oneplus 9`, `samsung galaxy s21`

## Clues:
1. The person who is an engineer is directly left of the person who uses a Samsung Galaxy S21.
2. The person who loves fantasy books is in the second house.
3. Alice is not in the second house.
4. Eric is the person who is a teacher.
5. The person who uses a Samsung Galaxy S21 is the person who loves fantasy books.
6. The person who uses an iPhone 13 is the person who loves science fiction books.
7. The person who loves science fiction books is somewhere to the left of the person who uses a OnePlus 9.
8. The person who uses a OnePlus 9 is Arnold.
9. The person who is a doctor is the person who loves mystery books.
10. The person who uses an iPhone 13 is the person who is a teacher.
"""

    solution = solve_zebra_puzzle(puzzle)

    assert solution is not None
    assert solution["Name_Eric"] == "house3"
    assert solution["Occupation_engineer"] == "house1"
    assert solution["Occupation_teacher"] == "house3"
    assert solution["BookGenre_fantasy"] == "house2"
    assert solution["PhoneModel_samsung_galaxy_s21"] == "house2"


def test_oracle_solves_child_height_music_and_right_of_aliases():
    puzzle = """There are 6 houses, numbered 1 to 6 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Bob`, `Alice`, `Peter`, `Eric`, `Arnold`, `Carol`
 - Each mother is accompanied by their child: `Fred`, `Timothy`, `Samantha`, `Alice`, `Meredith`, `Bella`
 - People have unique favorite music genres: `pop`, `hip hop`, `classical`, `jazz`, `rock`, `country`
 - People have unique heights: `average`, `very tall`, `tall`, `super tall`, `very short`, `short`

## Clues:
1. There is one house between the person's child is named Samantha and the person who is short.
2. The person's child is named Alice is Bob.
3. The person who loves country music is directly left of Arnold.
4. Alice is the person who is tall.
5. The person who loves pop music is Eric.
6. Bob is somewhere to the right of the person who is super tall.
7. The person's child is named Fred is Peter.
8. The person's child is named Bella is the person who loves hip-hop music.
9. The person who is the mother of Timothy is not in the sixth house.
10. The person who is super tall is somewhere to the right of the person who has an average height.
11. The person's child is named Alice is somewhere to the right of Arnold.
12. There is one house between the person who is short and the person who is very short.
13. The person who is very short is in the fifth house.
14. The person who loves jazz music is not in the fifth house.
15. Carol is somewhere to the left of the person who is the mother of Timothy.
16. The person who is very tall is not in the sixth house.
17. The person who loves classical music is in the sixth house.
18. The person who loves rock music is in the first house.
"""

    solution = solve_zebra_puzzle(puzzle)

    assert solution is not None
    assert solution["Name_Carol"] == "house1"
    assert solution["Name_Alice"] == "house6"
    assert solution["Name_Bob"] == "house4"
    assert solution["Child_Alice"] == "house4"
    assert solution["MusicGenre_classical"] == "house6"
    assert solution["Height_very_short"] == "house5"


def test_oracle_solves_mother_and_vacation_aliases():
    puzzle = """There are 6 houses, numbered 1 to 6 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Bob`, `Arnold`, `Carol`, `Alice`, `Peter`, `Eric`
 - The mothers' names in different houses are unique: `Sarah`, `Janelle`, `Aniya`, `Kailyn`, `Holly`, `Penny`
 - Each mother is accompanied by their child: `Fred`, `Samantha`, `Bella`, `Meredith`, `Alice`, `Timothy`
 - Each person prefers a unique type of vacation: `city`, `mountain`, `camping`, `beach`, `cruise`, `cultural`
 - People have unique favorite book genres: `romance`, `mystery`, `historical fiction`, `science fiction`, `biography`, `fantasy`

## Clues:
1. The person who loves beach vacations is not in the second house.
2. The person who loves fantasy books is somewhere to the left of Peter.
3. The person whose mother's name is Sarah is the person who prefers city breaks.
4. The person who enjoys camping trips is somewhere to the right of Peter.
5. The person who likes going on cruises is the person's child is named Meredith.
6. There is one house between the person who is the mother of Timothy and Eric.
7. The person whose mother's name is Janelle is not in the second house.
8. The person's child is named Fred is somewhere to the left of Eric.
9. The person who goes on cultural tours is in the fourth house.
10. The person whose mother's name is Janelle is not in the first house.
11. The person whose mother's name is Holly is somewhere to the right of the person who loves historical fiction books.
12. The person's child is named Bella is somewhere to the left of Alice.
13. Arnold is somewhere to the right of the person who loves fantasy books.
14. The person who loves mystery books is in the fourth house.
15. The person's child is named Alice is the person who enjoys camping trips.
16. The person whose mother's name is Kailyn is the person who likes going on cruises.
17. There are two houses between the person who loves fantasy books and The person whose mother's name is Aniya.
18. The person who loves fantasy books is Carol.
19. The person who likes going on cruises is the person who loves biography books.
20. The person who loves fantasy books is in the third house.
21. The person whose mother's name is Aniya is the person who loves romance books.
22. The person whose mother's name is Janelle is not in the fourth house.
23. The person's child is named Fred is not in the fourth house.
24. The person who loves biography books is not in the second house.
25. There are two houses between The person whose mother's name is Holly and Eric.
"""

    solution = solve_zebra_puzzle(puzzle)

    assert solution is not None
    assert solution["Name_Carol"] == "house3"
    assert solution["Mother_Aniya"] == "house6"
    assert solution["Vacation_cultural"] == "house4"
    assert solution["BookGenre_fantasy"] == "house3"


def test_oracle_returns_none_when_alias_points_to_missing_category_key():
    puzzle = """There are 2 houses, numbered 1 to 2 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - The people keep unique animals: `horse`, `cat`
 - The people keep unique animals: `dog`, `fish`

## Clues:
1. The horse owner is in the first house.
"""

    assert solve_zebra_puzzle(puzzle) is None


def test_oracle_solves_birthday_and_house_style_aliases():
    puzzle = """There are 4 houses, numbered 1 to 4 from left to right, as seen from across the street. Each house is occupied by a different person. Each house has a unique attribute for each of the following characteristics:
 - Each person has a unique name: `Eric`, `Arnold`, `Alice`, `Peter`
 - The mothers' names in different houses are unique: `Holly`, `Kailyn`, `Aniya`, `Janelle`
 - Each person has a unique birthday month: `april`, `feb`, `sept`, `jan`
 - Each person lives in a unique style of house: `ranch`, `colonial`, `victorian`, `craftsman`

## Clues:
1. Peter is the person whose birthday is in February.
2. The person whose birthday is in February is not in the fourth house.
3. The person whose birthday is in January is somewhere to the right of the person in a ranch-style home.
4. The person whose birthday is in January is directly left of Eric.
5. The person in a ranch-style home is the person whose birthday is in April.
6. The person whose mother's name is Janelle is the person whose birthday is in September.
7. The person in a ranch-style home and The person whose mother's name is Kailyn are next to each other.
8. Arnold is The person whose mother's name is Holly.
9. The person whose mother's name is Kailyn is directly left of the person residing in a Victorian house.
10. The person whose birthday is in January is the person in a Craftsman-style house.
"""

    solution = solve_zebra_puzzle(puzzle)

    assert solution is not None
    assert solution["Name_Peter"] == "house1"
    assert solution["Month_feb"] == "house1"
    assert solution["House_craftsman"] == "house3"
    assert solution["House_victorian"] == "house4"
